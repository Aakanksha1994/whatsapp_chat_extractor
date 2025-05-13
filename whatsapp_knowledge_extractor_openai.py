import re
import json
import os
import requests
from typing import List, Dict, Any
from collections import defaultdict
from dotenv import load_dotenv
import openai

# Load environment variables
load_dotenv()

# Set up OpenAI API
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    raise ValueError("OPENAI_API_KEY not found in environment variables")

# Basic WhatsApp chat parsing
def parse_whatsapp_chat(file_path: str) -> List[Dict[str, str]]:
    """Parse WhatsApp chat export file into structured data."""
    messages = []
    current_message = None
    line_count = 0
    parsed_count = 0
    
    # Pattern for date detection - very simple
    date_pattern = re.compile(r'^\[(\d{2}/\d{2}/\d{2})')
    
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
        for line in file:
            line_count += 1
            line = line.strip()
            if not line:
                continue
            
            # Check if this line starts a new message (has a date)
            if date_pattern.match(line):
                # Split by the closing bracket and colon
                try:
                    date_part = line.split(']')[0] + ']'
                    rest = line[len(date_part):].strip()
                    
                    if ':' in rest:
                        sender, message = rest.split(':', 1)
                        
                        # Add previous message if exists
                        if current_message:
                            messages.append(current_message)
                        
                        # Create new message
                        current_message = {
                            'date': date_part.strip('[]'),
                            'sender': sender.strip(),
                            'message': message.strip()
                        }
                        parsed_count += 1
                    else:
                        # System message without colon
                        if current_message:
                            messages.append(current_message)
                        current_message = {
                            'date': date_part.strip('[]'),
                            'sender': 'SYSTEM',
                            'message': rest.strip()
                        }
                        parsed_count += 1
                except:
                    # If parsing fails, add to previous message if exists
                    if current_message:
                        current_message['message'] += '\n' + line
            elif current_message:
                # Continuation of previous message
                current_message['message'] += '\n' + line
    
    # Add the last message
    if current_message:
        messages.append(current_message)
    
    print(f"Read {line_count} lines, parsed {parsed_count} messages")
    return messages

# Extract URLs from messages
def extract_urls(messages: List[Dict[str, str]]) -> List[str]:
    """Extract URLs from messages."""
    url_pattern = re.compile(r'https?://\S+')
    urls = set()
    for msg in messages:
        found = url_pattern.findall(msg['message'])
        urls.update(found)
    return list(urls)

# Get URL titles
def fetch_url_title(url: str) -> str:
    """Fetch the title of a webpage."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        
        # Use regex to extract title - more reliable than BeautifulSoup for some pages
        title_match = re.search(r'<title[^>]*>(.*?)</title>', resp.text, re.IGNORECASE | re.DOTALL)
        if title_match:
            title = title_match.group(1).strip()
            return title
        return url
    except Exception as e:
        print(f"Error fetching title for {url}: {e}")
        return url

# Extract knowledge with OpenAI
def extract_knowledge_with_openai(messages: List[Dict[str, str]], objective: str = "AI coding and development") -> Dict[str, Any]:
    """Use OpenAI to extract structured knowledge from chat messages."""
    # Prepare the chat content for OpenAI
    chat_content = "\n\n".join([f"{msg['sender']}: {msg['message']}" for msg in messages])
    
    # If the content is too long, truncate it
    if len(chat_content) > 100000:  # OpenAI's token limit is roughly 1/3 of character count
        chat_content = chat_content[:100000] + "\n...[truncated]"
    
    try:
        # Define the system prompt with the provided format
        system_prompt = f"""
        You are an AI assistant helping extract **only the valuable learning content** from WhatsApp chats. 
        Focus on tips, resources, insights, tools, links, or questions related to the objective: "{objective}".

        Ignore:
        - greetings, social messages, logistics
        - chatty responses like "okay", "cool", "thank you"

        Structure your answer as:
        - Summary of Key Learnings
        - List of Extracted Tips or Techniques
        - Mention any useful tools or resources

        Be brief, clear, and structured.
        
        Format your response as structured JSON with this schema:
        {{
            "categories": {{
                "Tips and Techniques": [
                    "tip 1",
                    "tip 2"
                ],
                "Tools and Resources": [
                    "resource 1",
                    "resource 2"
                ]
            }},
            "summary": "A concise summary of the main technical topics and value from this chat"
        }}
        """
        
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": chat_content}
            ],
            temperature=0.2,  # Low temperature for more structured output
            response_format={"type": "json_object"}  # Request JSON response
        )
        
        # Parse the JSON response
        result = json.loads(response.choices[0].message.content)
        return result
    
    except Exception as e:
        print(f"Error using OpenAI API: {e}")
        # Fallback to a basic structure with error message
        return {
            "categories": {
                "Error": [f"Failed to process with OpenAI: {str(e)}"]
            },
            "summary": "Error processing chat with OpenAI."
        }

# Generate markdown from the extracted knowledge
def generate_markdown_from_knowledge(knowledge: Dict[str, Any], urls: List[str], url_titles: List[Dict[str, str]]) -> str:
    """Convert the extracted knowledge to a formatted Markdown document."""
    markdown = "# AI Coding Knowledge Extraction\n\n"
    
    # Add the summary
    if "summary" in knowledge:
        markdown += "## Summary\n\n"
        markdown += f"{knowledge['summary']}\n\n"
    
    # Add categories and tips
    if "categories" in knowledge:
        categories = knowledge["categories"]
        for category, tips in categories.items():
            if tips:  # Only include categories with tips
                markdown += f"## {category}\n"
                markdown += f"{len(tips)} tips\n\n"
                
                for tip in tips:
                    markdown += f"- {tip}\n"
                
                markdown += "\n"
    
    # Add resource links
    if urls:
        markdown += "## Useful Resources\n\n"
        url_dict = {item['url']: item['title'] for item in url_titles}
        
        for url in urls:
            title = url_dict.get(url, url)
            if title == url:
                markdown += f"- [{url}]({url})\n"
            else:
                markdown += f"- [{title}]({url})\n"
    
    return markdown 