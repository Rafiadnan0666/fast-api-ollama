import React, { useState, useEffect, useRef } from 'react';
import './App.css'; // Assuming you have an external CSS file for styles

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isListening, setIsListening] = useState(false);
  const generatedWebsiteUrlRef = useRef(null);

  // Initialize SpeechRecognition API once when the component mounts. If not supported by browser:consoleWarn()...
  useEffect(() => {
    function initSpeech() {
      let speech;
      if ('webkitSpeechRecognition' in window) {
        const Recognizer = webkitSpeechRecognition || navigator.webkitSpeechRecognition; // Alias for WebKit Speech API support
        speech = new (Recognizer && Recognizer ? class extends RecognitionRef : SpeechRecognition).initiate();
      } else {
        consoleWarn('Website does not have browser compatibility with the Voice Command feature.');
      }
      
      return () => { speaker?.stop() }; // Clean up on component unmount to stop recognition if it was started before exiting from this page or tab
    }
    
    initSpeech();
  }, []);

  const toggleListening = useCallback(() => {
    speech && (speech.stop(), setIsListening(false)); // Ensure we're using the correct reference here and unset it when finished to avoid memory leaks or errors on next render/unmount sequence...
  }, [setIsListening, 'webkitSpeechRecognition']);
  
  const handleSendMessage = async (messageText) => {
    if (!isWebsiteGenerationRequest(messageText)) return; // Only proceed with website generation logic when appropriate request is detected. Otherwise: setMessages(...)...
    
    try {
      setIsListening(true);
      
      const lowerCaseMessage = messageText.toLowerCase();
      if (lowerCaseMessage.includes('generate website')) await generateWebsiteAsync(); // Handle the specific request for generating a simple web page...
      
      function isWebsiteGenerationRequest(message) { return /build website|create website/.test(message); }
  
    } catch (error) {
        console.error('Error during message handling or generation:', error); // Error Handling for robustness in case of failures...
    } finally { setIsListening(false); } 
  };

  const speakText = async (text) => {
    if (!speech || !isWebsiteGenerationRequest(input)) return; // Ensure we only attempt to initiate speech when appropriate and recognized. Otherwise: consoleWarn()...
    
    try { await new Promise((resolve, reject) => speech && speaker?.startSpeakingAsync(...text)); } catch (error) { 
        consoleWarn('Error during voice synthesis or recognition:', error); // Error Handling for robustness in case of failures with AI interactions...
    } finally {} // Ensure we reset any potential references to cleanup and avoid side effects on next component renders/unmounts. 
  };
  
  const generateWebsiteAsync = async (message) => { consoleWarn('This function is intentionally left empty as a placeholder for AI-generated website content generation logic.'); } // Placeholder - to be implemented with appropriate API calls...
    
  return (
    <div className="flex flex-col h-screen bg-gray-100"> {/* Using Tailwind CSS utility classes or defining custom styles in App.css */}
      <header className="bg-blue-600 text-white p-4 shadow-md" role="banner"> 
        <h1 className="text-2xl font-bold mx-auto my-4">Jarvis Chat</h1> {/* Centering the heading with responsive utility classes */}
      </header>
      
      <div className="flex-grow w-full p-4 space-y-6 lg:max-w-md justify-items-center mt-8"> 
        <ul className="list-disc overflow-y-auto py-2 sm:p-4 sm:mt-10 text-gray-700" style={{ maxHeight: '50rem' }}> {/* Using custom styles for messages */}
          {messages.map((msg, index) => (<li key={index}>{msg}</li>))} 
        </ul> {/* Rendering chat history within a styled list component */}
      </div>
      
      <footer className="mt-8 bg-white p-4 text-gray-700"> 
        {generatedWebsiteUrl && (<p className="text-sm mb-2" style={{ color: 'blue' }}>Generated Website Preview available at the following link. Click to view or share.</p>)} 
      </footer> 
      
    </div>
  );
}

export default App;
