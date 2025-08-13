import os
import logging
import json
from contextlib import asynccontextmanager
from uuid import uuid4
from datetime import datetime
import pytz

import uvicorn
import ollama
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

# For file operations
import aiofiles

# --- Configuration Setup ---

load_dotenv()

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("api_service.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Environment Variable & Security Setup ---

API_ACCESS_KEY = os.getenv("API_ACCESS_KEY")
if not API_ACCESS_KEY:
    logger.warning("API_ACCESS_KEY environment variable not set. The API will not require authentication.")

API_KEY_NAME = "X-API-KEY"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

# --- Pydantic Models ---

class AskRequest(BaseModel):
    prompt: str = Field(..., description="The prompt to send to the model.", example="Explain the importance of bees.")
    model: str = Field("phi3:mini", description="The Ollama model to use.", example="phi3:mini")
    options: Optional[Dict[str, Any]] = Field(None, description="Ollama generation options (e.g., temperature, top_p).", example={"temperature": 0.8})
    json_format: bool = Field(True, description="Ensure the final output is a JSON object.")

class AskResponse(BaseModel):
    request_id: str
    timestamp: str
    response: Dict[str, Any]

class ErrorResponse(BaseModel):
    error: str
    code: int
    request_id: Optional[str] = None
    details: Optional[str] = None

class HealthCheckResponse(BaseModel):
    status: str
    ollama_status: str
    timestamp: str

class FileOperationRequest(BaseModel):
    path: str = Field(..., description="The absolute path to the file.", example="/app/data/example.txt")
    content: str = Field(..., description="The content to write to the file.", example="Hello, world!")

class FileOperationResponse(BaseModel):
    message: str
    path: str
    timestamp: str

class WebsiteGenerationRequest(BaseModel):
    html_content: str = Field(..., description="The HTML content for the website.")
    css_content: Optional[str] = Field(None, description="The CSS content for the website.")
    js_content: Optional[str] = Field(None, description="The JavaScript content for the website.")

class WebsiteGenerationResponse(BaseModel):
    message: str
    url: str
    timestamp: str

# --- Application Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Check Ollama connection on startup."""
    app.state.is_ollama_ready = False
    try:
        logger.info("Checking connection to Ollama...")
        ollama.list()
        app.state.is_ollama_ready = True
        logger.info("Ollama connection successful.")
    except Exception as e:
        logger.critical(f"Failed to connect to Ollama on startup. Please ensure Ollama is running. Error: {e}")
    yield
    logger.info("Shutting down API service.")

# --- FastAPI Application Setup ---

app = FastAPI(
    title="Robust Ollama API Service",
    description="A resilient API service for Ollama models with structured JSON output.",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Helper Functions ---

def get_current_timestamp() -> str:
    return datetime.now(pytz.utc).isoformat()

async def validate_api_key(api_key: str = Depends(api_key_header)):
    """Dependency to validate the API key from the request header."""
    if not API_ACCESS_KEY:
        # If no key is set in the environment, skip validation
        return
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API Key is missing")
    if api_key != API_ACCESS_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")

# --- Exception Handlers ---

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    logger.error(f"Unhandled Exception - ID: {request_id} - Path: {request.url.path}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(error="Internal Server Error", code=500, request_id=request_id, details=str(exc)).model_dump()
    )

# --- API Endpoints ---

@app.get("/health", response_model=HealthCheckResponse, tags=["Health"])
async def health_check():
    """Provides the operational status of the API and the Ollama connection."""
    ollama_status = "ready" if app.state.is_ollama_ready else "unavailable"
    return HealthCheckResponse(
        status="running",
        ollama_status=ollama_status,
        timestamp=get_current_timestamp()
    )

@app.post("/generate", response_model=AskResponse, tags=["Generation"], dependencies=[Depends(validate_api_key)])
async def generate_content(request: AskRequest, http_request: Request):
    """
    Generate structured JSON content using an Ollama model.
    This endpoint is protected by an API key if API_ACCESS_KEY is set.
    """
    request_id = http_request.headers.get("X-Request-ID", str(uuid4()))

    if not app.state.is_ollama_ready:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Ollama service is not available.")

    logger.info(f"Processing request {request_id} with model {request.model}")

    try:
        # Add instruction for JSON format if requested
        prompt = request.prompt
        if request.json_format:
            prompt += ". IMPORTANT: Your response MUST be a single, valid JSON object."

        # Generate content using Ollama
        response = ollama.chat(
            model=request.model,
            messages=[{'role': 'user', 'content': prompt}],
            stream=False,
            options=request.options
        )

        content = response['message']['content']

        # Attempt to parse the model's response as JSON
        try:
            # Clean up potential markdown code fences
            if content.startswith("```json"):
                content = content.strip("```json\n").strip("```")
            json_response = json.loads(content)
        except json.JSONDecodeError:
            logger.warning(f"Request {request_id}: Model response was not valid JSON. Wrapping raw content.")
            json_response = {"response_text": content}

        logger.info(f"Request {request_id} completed successfully.")

        return AskResponse(
            request_id=request_id,
            timestamp=get_current_timestamp(),
            response=json_response
        )

    except ollama.ResponseError as e:
        logger.error(f"Request {request_id}: Ollama API error: {e.error}")
        raise HTTPException(status_code=e.status_code, detail=f"Ollama error: {e.error}")
    except Exception as e:
        logger.error(f"Request {request_id}: An unexpected error occurred during generation.", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred: {str(e)}")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            # Process the incoming message (e.g., send to Ollama)
            # For now, just echo it back
            await websocket.send_text(f"Message text was: {data}")
    except WebSocketDisconnect:
        logger.info("Client disconnected from WebSocket.")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")

@app.post("/file", response_model=FileOperationResponse, tags=["File Operations"], dependencies=[Depends(validate_api_key)])
async def file_operation(request: FileOperationRequest, http_request: Request):
    request_id = http_request.headers.get("X-Request-ID", str(uuid4()))
    logger.info(f"Processing file operation request {request_id} for path: {request.path}")

    try:
        async with aiofiles.open(request.path, mode="w") as f:
            await f.write(request.content)

        logger.info(f"File operation {request_id} completed successfully for path: {request.path}")
        return FileOperationResponse(
            message="File written successfully",
            path=request.path,
            timestamp=get_current_timestamp()
        )
    except Exception as e:
        logger.error(f"File operation {request_id} failed for path: {request.path}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"File operation failed: {str(e)}")

@app.post("/generate_website", response_model=WebsiteGenerationResponse, tags=["Website Generation"], dependencies=[Depends(validate_api_key)])
async def generate_website(request: WebsiteGenerationRequest, http_request: Request):
    request_id = http_request.headers.get("X-Request-ID", str(uuid4()))
    logger.info(f"Processing website generation request {request_id}")

    try:
        # Create a unique directory for the website
        site_id = str(uuid4())
        site_dir = os.path.join("..", "frontend", "public", "websites", site_id)
        os.makedirs(site_dir, exist_ok=True)

        # Write HTML content
        html_path = os.path.join(site_dir, "index.html")
        async with aiofiles.open(html_path, mode="w") as f:
            await f.write(request.html_content)

        # Write CSS content if provided
        if request.css_content:
            css_path = os.path.join(site_dir, "style.css")
            async with aiofiles.open(css_path, mode="w") as f:
                await f.write(request.css_content)
            # Inject CSS link into HTML if not already present
            if "<link rel=\"stylesheet\" href=\"style.css\">" not in request.html_content:
                with open(html_path, "r+") as f:
                    content = f.read()
                    f.seek(0)
                    f.write(content.replace("</head>", "  <link rel=\"stylesheet\" href=\"style.css\">\n</head>"))

        # Write JS content if provided
        if request.js_content:
            js_path = os.path.join(site_dir, "script.js")
            async with aiofiles.open(js_path, mode="w") as f:
                await f.write(request.js_content)
            # Inject JS script into HTML if not already present
            if "<script src=\"script.js\"></script>" not in request.html_content:
                with open(html_path, "r+") as f:
                    content = f.read()
                    f.seek(0)
                    f.write(content.replace("</body>", "  <script src=\"script.js\"></script>\n</body>"))

        # Construct the URL
        # Assuming the frontend serves static files from /public
        website_url = f"/websites/{site_id}/index.html"

        logger.info(f"Website generation request {request_id} completed successfully. URL: {website_url}")
        return WebsiteGenerationResponse(
            message="Website generated successfully",
            url=website_url,
            timestamp=get_current_timestamp()
        )
    except Exception as e:
        logger.error(f"Website generation request {request_id} failed.", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Website generation failed: {str(e)}")


# --- Main Execution ---

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8001))
    logger.info(f"Starting server on http://localhost:{port}")
    uvicorn.run(app, host="localhost", port=port)