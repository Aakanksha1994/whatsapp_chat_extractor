from flask import Flask, request, render_template, redirect, url_for, session
import os
import tempfile
from whatsapp_knowledge_extractor_simple import parse_whatsapp_chat, extract_urls, extract_coding_tips, fetch_url_title

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max file size

@app.route('/', methods=['GET', 'POST'])
def index():
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
                
                # Store results in session
                session['link_titles'] = link_titles
                session['coding_tips'] = coding_tips
                session['message_count'] = len(messages)
                
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
    # Get results from session
    link_titles = session.get('link_titles', [])
    coding_tips = session.get('coding_tips', [])
    message_count = session.get('message_count', 0)
    
    if not coding_tips and not link_titles:
        return redirect(url_for('index'))
    
    return render_template(
        'results.html',
        link_titles=link_titles,
        coding_tips=coding_tips,
        message_count=message_count
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True) 