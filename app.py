"""
App entry point for Railway deployment 
This is a standard name many Python platforms look for
"""
from flask import Flask, request, render_template, redirect, url_for, session, Response
import os
import re
from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup
import tempfile
from collections import defaultdict
import html
import json
import uuid
import socket

# Try to import advanced module, fall back to simple if it fails
try:
    from whatsapp_knowledge_extractor import parse_whatsapp_chat, extract_urls, extract_coding_tips, fetch_url_title, categorize_tips
    print("Using advanced ML-based extractor")
except ImportError:
    print("Advanced extractor unavailable, falling back to simple extractor")
    from whatsapp_knowledge_extractor_simple import parse_whatsapp_chat, extract_urls, extract_coding_tips, fetch_url_title, categorize_tips

# Import OpenAI-specific function for optional OpenAI processing
try:
    from whatsapp_knowledge_extractor_openai import extract_knowledge_with_openai, generate_markdown_from_knowledge
    OPENAI_AVAILABLE = True
    print("OpenAI integration available")
except ImportError:
    OPENAI_AVAILABLE = False
    print("OpenAI integration not available")

# Function to export to markdown
def export_to_markdown(categorized_tips, urls, link_titles):
    """Create a Markdown export of the categorized tips and resources."""
    markdown = "# AI Coding Knowledge Extraction\n\n"
    
    # Add tips by category
    for category, tips in categorized_tips.items():
        markdown += f"## {category}\n"
        markdown += f"{len(tips)} tips\n\n"
        
        for tip in tips:
            # Clean up the tip text
            content = tip['content'].strip()
            markdown += f"- {content}\n"
        
        markdown += "\n"
    
    # Add resource links
    if urls:
        markdown += "## Useful Resources\n\n"
        url_dict = {item['url']: item['title'] for item in link_titles}
        
        for url in urls:
            title = url_dict.get(url, url)
            if title == url:
                markdown += f"- [{url}]({url})\n"
            else:
                markdown += f"- [{title}]({url})\n"
                
    return markdown

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
app.config['RESULTS_FOLDER'] = tempfile.mkdtemp()
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max file size

# Add a better summarization function since we can't use BART
def better_summarize(messages, max_length=500):
    """Better text-based summarization that generates a concise summary"""
    
    # Extract key metrics
    total_messages = len(messages)
    unique_senders = len(set(msg['sender'] for msg in messages))
    
    # Get date range
    try:
        first_date = messages[0]['date'] if messages else "Unknown"
        last_date = messages[-1]['date'] if messages else "Unknown"
        date_range = f"{first_date} to {last_date}"
    except:
        date_range = "Unknown date range"
    
    # Count message types (simple approximation)
    link_count = 0
    question_count = 0
    long_message_count = 0
    
    for msg in messages:
        if "http" in msg['message']:
            link_count += 1
        if "?" in msg['message']:
            question_count += 1
        if len(msg['message'].split()) > 20:
            long_message_count += 1
    
    # Find frequent words for topics (excluding common words)
    common_words = {"the", "and", "is", "in", "to", "of", "a", "for", "it", "this", "that", "you", "on", "with", "be", "are", "i", "was", "have", "from"}
    word_count = {}
    
    for msg in messages:
        for word in msg['message'].lower().split():
            # Clean the word of punctuation
            word = ''.join(c for c in word if c.isalnum())
            if word and len(word) > 3 and word not in common_words:
                word_count[word] = word_count.get(word, 0) + 1
    
    # Get top topics
    topics = [word for word, count in sorted(word_count.items(), key=lambda x: x[1], reverse=True)[:5] if count > 1]
    
    # Create the summary
    summary = f"Chat Summary ({total_messages} messages from {unique_senders} participants, {date_range}):\n\n"
    
    if topics:
        summary += f"Main topics: {', '.join(topics)}\n\n"
    
    summary += f"This chat contains {link_count} links, {question_count} questions, and {long_message_count} detailed messages.\n\n"
    
    # Add a few representative messages (5 longest that aren't too long)
    sorted_messages = sorted(messages, key=lambda m: len(m['message']), reverse=True)
    representative = []
    
    for msg in sorted_messages:
        # Skip very long messages and very short ones
        if 20 < len(msg['message'].split()) < 100 and len(representative) < 3:
            # Truncate each message
            text = msg['message'][:100] + ("..." if len(msg['message']) > 100 else "")
            representative.append(f"{msg['sender']}: {text}")
    
    if representative:
        summary += "Sample messages:\n" + "\n".join(representative)
    
    return summary

# Add a new route for markdown export
@app.route('/export_markdown')
def export_markdown():
    # Get result ID from session
    result_id = session.get('result_id')
    
    if not result_id:
        return redirect(url_for('index'))
    
    # Load results from temporary file
    result_file = os.path.join(app.config['RESULTS_FOLDER'], f"{result_id}.json")
    
    if not os.path.exists(result_file):
        return redirect(url_for('index'))
    
    with open(result_file, 'r') as f:
        results = json.load(f)
    
    # Generate Markdown
    markdown_content = export_to_markdown(
        results['categorized_tips'],
        [item['url'] for item in results['link_titles']],
        results['link_titles']
    )
    
    # Return as a downloadable file
    return Response(
        markdown_content,
        mimetype='text/markdown',
        headers={'Content-Disposition': 'attachment;filename=ai_coding_knowledge.md'}
    )

# Update results.html to include a link to export as Markdown
@app.route('/', methods=['GET', 'POST'])
def index():
    # Check if this is a direct markdown request
    if request.args.get('format') == 'markdown' and request.method == 'POST':
        if 'file' not in request.files:
            return "No file selected", 400
        
        file = request.files['file']
        
        if file.filename == '':
            return "No file selected", 400
        
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'chat.txt')
        file.save(filepath)
        
        try:
            # Parse the WhatsApp chat
            messages = parse_whatsapp_chat(filepath)
            
            # Use OpenAI if available and requested
            if OPENAI_AVAILABLE and request.form.get('use_openai'):
                urls = extract_urls(messages)
                link_titles = []
                for url in urls:
                    title = fetch_url_title(url)
                    link_titles.append({'url': url, 'title': title})
                
                # Extract with OpenAI
                knowledge = extract_knowledge_with_openai(messages)
                markdown_content = generate_markdown_from_knowledge(knowledge, urls, link_titles)
            else:
                # Extract URLs and their titles
                urls = extract_urls(messages)
                link_titles = []
                for url in urls:
                    title = fetch_url_title(url)
                    link_titles.append({'url': url, 'title': title})
                
                # Extract coding tips
                coding_tips = extract_coding_tips(messages)
                
                # Categorize the coding tips
                categorized_tips = categorize_tips(coding_tips)
                
                # Generate Markdown directly
                markdown_content = export_to_markdown(
                    categorized_tips,
                    urls,
                    link_titles
                )
            
            # Return as a downloadable file
            return Response(
                markdown_content,
                mimetype='text/markdown',
                headers={'Content-Disposition': 'attachment;filename=ai_coding_knowledge.md'}
            )
            
        except Exception as e:
            return f"Error processing file: {str(e)}", 400
        finally:
            # Clean up the temporary file
            if os.path.exists(filepath):
                os.remove(filepath)
    
    # Regular web interface flow
    if request.method == 'POST':
        # Check if a file was uploaded
        if 'file' not in request.files:
            return render_template('index.html', error="No file selected", openai_available=OPENAI_AVAILABLE)
        
        file = request.files['file']
        
        # If user submits without selecting a file
        if file.filename == '':
            return render_template('index.html', error="No file selected", openai_available=OPENAI_AVAILABLE)
        
        if file:
            # Save the file to a temporary location
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'chat.txt')
            file.save(filepath)
            
            try:
                # Process with focus on technical content only
                messages = parse_whatsapp_chat(filepath)
                
                # Use OpenAI if available and requested
                if OPENAI_AVAILABLE and request.form.get('use_openai'):
                    # Extract URLs and their titles
                    urls = extract_urls(messages)
                    link_titles = []
                    for url in urls:
                        title = fetch_url_title(url)
                        link_titles.append({'url': url, 'title': title})
                    
                    # Extract with OpenAI
                    knowledge = extract_knowledge_with_openai(messages)
                    
                    # Create a unique ID for this result
                    result_id = str(uuid.uuid4())
                    
                    # Store results in a temporary file
                    results = {
                        'link_titles': link_titles,
                        'categorized_tips': knowledge['categories'],
                        'message_count': len(messages),
                        'chat_summary': knowledge['summary']
                    }
                else:
                    # Extract URLs and their titles
                    urls = extract_urls(messages)
                    link_titles = []
                    for url in urls:
                        title = fetch_url_title(url)
                        link_titles.append({'url': url, 'title': title})
                    
                    # Extract only technical coding tips
                    coding_tips = extract_coding_tips(messages)
                    
                    # Categorize the coding tips
                    categorized_tips = categorize_tips(coding_tips)
                    
                    # Create a simple summary
                    chat_summary = better_summarize(messages)
                    
                    # Create a unique ID for this result
                    result_id = str(uuid.uuid4())
                    
                    # Store results in a temporary file
                    results = {
                        'link_titles': link_titles,
                        'coding_tips': coding_tips,
                        'categorized_tips': categorized_tips,
                        'message_count': len(messages),
                        'chat_summary': chat_summary
                    }
                
                # Save to a temporary file
                result_file = os.path.join(app.config['RESULTS_FOLDER'], f"{result_id}.json")
                with open(result_file, 'w') as f:
                    json.dump(results, f)
                
                # Store only the ID in session
                session['result_id'] = result_id
                
                return redirect(url_for('results'))
            
            except Exception as e:
                return render_template('index.html', error=f"Error processing file: {str(e)}", openai_available=OPENAI_AVAILABLE)
            finally:
                # Clean up the temporary file
                if os.path.exists(filepath):
                    os.remove(filepath)
    
    return render_template('index.html', openai_available=OPENAI_AVAILABLE)

@app.route('/results')
def results():
    # Get result ID from session
    result_id = session.get('result_id')
    
    if not result_id:
        return redirect(url_for('index'))
    
    # Load results from temporary file
    result_file = os.path.join(app.config['RESULTS_FOLDER'], f"{result_id}.json")
    
    if not os.path.exists(result_file):
        return redirect(url_for('index'))
    
    with open(result_file, 'r') as f:
        results = json.load(f)
    
    return render_template(
        'results.html',
        link_titles=results['link_titles'],
        coding_tips=results.get('coding_tips', []),  # May not exist in OpenAI version
        categorized_tips=results['categorized_tips'],
        message_count=results['message_count'],
        chat_summary=results['chat_summary']
    )

def find_available_port(preferred_ports=[8888, 8080, 5000, 3000]):
    """Try to find an available port from the list of preferred ports."""
    for port in preferred_ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('localhost', port))
        sock.close()
        if result != 0:  # Port is available
            return port
    
    # If no preferred port is available, find a random available port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('localhost', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port

if __name__ == "__main__":
    import os
    preferred_port = int(os.environ.get("PORT", 8888))
    port = find_available_port([preferred_port, 8080, 5000, 3000])
    print(f"Starting server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True) 