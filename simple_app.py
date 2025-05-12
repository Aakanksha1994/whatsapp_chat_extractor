from flask import Flask, request, Response, jsonify, send_from_directory
import os
import tempfile
import re
from typing import List, Dict, Any

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max file size

def parse_whatsapp_chat(file_path: str) -> List[Dict[str, str]]:
    """Parse WhatsApp chat export into structured messages."""
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

def extract_urls(messages: List[Dict[str, str]]) -> List[str]:
    """Extract URLs from messages."""
    url_pattern = re.compile(r'https?://\S+')
    urls = set()
    for msg in messages:
        found = url_pattern.findall(msg['message'])
        urls.update(found)
    return list(urls)

@app.route('/')
def index():
    """Simple home page that doesn't rely on templates"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>WhatsApp Chat Analyzer</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
            h1 { color: #4CAF50; }
            form { margin: 20px 0; }
            .button { background: #4CAF50; color: white; padding: 10px 15px; border: none; cursor: pointer; }
        </style>
    </head>
    <body>
        <h1>WhatsApp Chat Analyzer</h1>
        <p>Upload your WhatsApp chat export (.txt file) to extract coding tips and links.</p>
        
        <form action="/upload" method="post" enctype="multipart/form-data">
            <input type="file" name="file" accept=".txt" required>
            <button type="submit" class="button">Analyze Chat</button>
        </form>
    </body>
    </html>
    """
    return html

@app.route('/upload', methods=['POST'])
def upload():
    """Handle file upload without templates"""
    if 'file' not in request.files:
        return "No file part", 400
    
    file = request.files['file']
    if file.filename == '':
        return "No selected file", 400
    
    if file:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'chat.txt')
        try:
            file.save(filepath)
            messages = parse_whatsapp_chat(filepath)
            
            # Extract URLs without classification
            links = extract_urls(messages)
            
            # Prepare results
            results = {
                'message_count': len(messages),
                'link_count': len(links),
                'links': links
            }
            
            # Build HTML response
            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Chat Analysis Results</title>
                <style>
                    body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
                    h1 {{ color: #4CAF50; }}
                    .summary {{ background: #E8F5E9; padding: 10px; border-radius: 5px; margin: 20px 0; }}
                    .link-list {{ list-style-type: none; padding: 0; }}
                    .link-item {{ margin-bottom: 10px; padding: 10px; border-radius: 5px; background: #F5F5F5; }}
                    a {{ color: #2196F3; text-decoration: none; }}
                    a:hover {{ text-decoration: underline; }}
                    .back {{ display: inline-block; margin-top: 20px; color: white; background: #4CAF50; padding: 10px 15px; text-decoration: none; }}
                </style>
            </head>
            <body>
                <h1>WhatsApp Chat Analysis Results</h1>
                
                <div class="summary">
                    Analyzed <strong>{len(messages)}</strong> messages and found <strong>{len(links)}</strong> links.
                </div>
                
                <h2>Links from Chat</h2>
                <ul class="link-list">
                    {"".join([f'<li class="link-item"><a href="{link}" target="_blank">{link}</a></li>' for link in links])}
                </ul>
                
                <a href="/" class="back">← Back to Upload</a>
            </body>
            </html>
            """
            
            # Clean up
            if os.path.exists(filepath):
                os.remove(filepath)
                
            return html
            
        except Exception as e:
            app.logger.error(f"Error processing file: {str(e)}")
            return f"Error processing file: {str(e)}", 500
    
    return "Unknown error", 500

@app.route('/debug')
def debug():
    """A simple debug endpoint that just shows if the app is running"""
    return jsonify({
        'status': 'ok',
        'working_directory': os.getcwd(),
        'files': os.listdir('.'),
        'env': {k: v for k, v in os.environ.items() if not k.startswith('_')}
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    app.run(host='0.0.0.0', port=port) 