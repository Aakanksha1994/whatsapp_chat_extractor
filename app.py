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

# Import our simplified chat parsing functions instead
from whatsapp_knowledge_extractor_simple import parse_whatsapp_chat, extract_urls, extract_coding_tips, fetch_url_title, categorize_tips, export_to_markdown

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
            return render_template('index.html', error="No file selected")
        
        file = request.files['file']
        
        # If user submits without selecting a file
        if file.filename == '':
            return render_template('index.html', error="No file selected")
        
        if file:
            # Save the file to a temporary location
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'chat.txt')
            file.save(filepath)
            
            try:
                # Process with focus on technical content only
                messages = parse_whatsapp_chat(filepath)
                
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
                
                # Store results in a temporary file instead of session
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
                return render_template('index.html', error=f"Error processing file: {str(e)}")
            finally:
                # Clean up the temporary file
                if os.path.exists(filepath):
                    os.remove(filepath)
    
    return render_template('index.html')

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
        coding_tips=results['coding_tips'],
        categorized_tips=results['categorized_tips'],
        message_count=results['message_count'],
        chat_summary=results['chat_summary']
    )

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8888))
    app.run(host="0.0.0.0", port=port, debug=True) 