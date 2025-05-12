#!/usr/bin/env python3
import sys
import os
import re
from typing import List, Dict

def parse_chat(file_path: str) -> List[Dict]:
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

def main():
    if len(sys.argv) < 2:
        print("Usage: python parse_chat.py <chat_file>")
        return
    
    chat_file = sys.argv[1]
    if not os.path.exists(chat_file):
        print(f"Error: File {chat_file} not found")
        return
    
    messages = parse_chat(chat_file)
    print(f"Successfully parsed {len(messages)} messages")
    
    # Print first 5 messages
    for i, msg in enumerate(messages[:5]):
        print(f"\nMessage {i+1}:")
        print(f"Date: {msg['date']}")
        print(f"Sender: {msg['sender']}")
        print(f"Message: {msg['message'][:100]}..." if len(msg['message']) > 100 else f"Message: {msg['message']}")

if __name__ == "__main__":
    main() 