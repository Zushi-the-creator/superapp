#!/bin/bash

# NASDAQ Super App - Quick Start Script
# This script automates the setup and launch process

set -e

echo "🚀 NASDAQ Super App - Quick Start"
echo "=================================="
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first:"
    echo "   https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first:"
    echo "   https://docs.docker.com/compose/install/"
    exit 1
fi

echo "✅ Docker and Docker Compose found"
echo ""

# Start services
echo "📦 Starting all services..."
docker-compose up -d

echo ""
echo "⏳ Waiting for services to initialize (30 seconds)..."
sleep 30

# Check if Ollama is running
echo "🤖 Checking Ollama status..."
if docker ps | grep -q ollama; then
    echo "✅ Ollama is running"

    # Pull LLM model
    echo ""
    echo "📥 Pulling Llama 3.2 model (this may take a few minutes)..."
    docker exec $(docker ps -q -f name=ollama) ollama pull llama3.2

    echo "✅ Model downloaded successfully"
else
    echo "⚠️  Ollama container not found. Check docker-compose logs."
fi

echo ""
echo "=================================="
echo "🎉 Setup Complete!"
echo "=================================="
echo ""
echo "Access the application:"
echo "  Frontend:  http://localhost:3000"
echo "  Backend:   http://localhost:8000"
echo "  API Docs:  http://localhost:8000/docs"
echo ""
echo "⏱️  The scanner will start in 30-60 seconds."
echo "    Watch the live feed populate with data!"
echo ""
echo "📝 Tips:"
echo "  - View logs: docker-compose logs -f"
echo "  - Stop app:  docker-compose down"
echo "  - Restart:   docker-compose restart"
echo ""
echo "Happy trading! 📈🚀"
