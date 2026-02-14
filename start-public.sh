#!/bin/bash

echo "🚀 Starting NASDAQ Super App with Public Link..."
echo ""

# Check if ngrok is installed
if ! command -v ngrok &> /dev/null
then
    echo "📦 Installing ngrok..."
    brew install ngrok
fi

# Start docker-compose in background
echo "🐳 Starting Docker containers..."
docker-compose up -d

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 10

# Check if services are running
echo "✅ Checking services..."
curl -s http://localhost:8000/ > /dev/null && echo "  Backend: Running" || echo "  Backend: Failed"
curl -s http://localhost:3000/ > /dev/null && echo "  Frontend: Running" || echo "  Frontend: Failed"

echo ""
echo "🌐 Creating public link with ngrok..."
echo ""
echo "======================================"
echo "Your app will be available at the URL shown below"
echo "Share this link with anyone!"
echo "======================================"
echo ""

# Start ngrok
ngrok http 3000
