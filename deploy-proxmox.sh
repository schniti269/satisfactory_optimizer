#!/bin/bash
# Deployment script for Satisfactory Optimizer on Proxmox

set -e

echo "🚀 Satisfactory Optimizer - Proxmox Deployment"
echo "=============================================="

# Configuration
CONTAINER_NAME="${CONTAINER_NAME:-satisfactory-optimizer}"
PORT="${PORT:-5000}"
WATCH_DIR="${WATCH_DIR:-/mnt/satisfactory/saves}"
DATA_DIR="${DATA_DIR:-./satisfactory-data}"
REPO="${REPO:-https://github.com/schniti269/satisfactory_optimizer.git}"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}Configuration:${NC}"
echo "  Container: $CONTAINER_NAME"
echo "  Port: $PORT"
echo "  Watch Dir: $WATCH_DIR"
echo "  Data Dir: $DATA_DIR"
echo ""

# Step 1: Clone or pull repo
if [ ! -d "satisfactory_optimizer" ]; then
    echo -e "${BLUE}📦 Cloning repository...${NC}"
    git clone $REPO satisfactory_optimizer
    cd satisfactory_optimizer
else
    echo -e "${BLUE}📦 Pulling latest changes...${NC}"
    cd satisfactory_optimizer
    git pull origin master
fi

# Step 2: Create watch directory
echo -e "${BLUE}📂 Creating watch directory...${NC}"
mkdir -p $WATCH_DIR
chmod 755 $WATCH_DIR
echo -e "${GREEN}✓ Watch directory: $WATCH_DIR${NC}"

# Step 3: Create data directory
echo -e "${BLUE}📂 Creating data directory...${NC}"
mkdir -p $DATA_DIR
chmod 755 $DATA_DIR
echo -e "${GREEN}✓ Data directory: $DATA_DIR${NC}"

# Step 4: Build Docker image
echo -e "${BLUE}🐳 Building Docker image...${NC}"
docker build -t $CONTAINER_NAME:latest .
echo -e "${GREEN}✓ Docker image built${NC}"

# Step 5: Stop existing container (if running)
if docker ps --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${YELLOW}⚠ Stopping existing container...${NC}"
    docker stop $CONTAINER_NAME
fi

# Step 6: Remove existing container (if exists)
if docker ps -a --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${YELLOW}⚠ Removing existing container...${NC}"
    docker rm $CONTAINER_NAME
fi

# Step 7: Start new container
echo -e "${BLUE}🚀 Starting new container...${NC}"
docker run -d \
    --name $CONTAINER_NAME \
    -p $PORT:5000 \
    -v $WATCH_DIR:/app/watch:ro \
    -v $DATA_DIR:/app/webapp \
    -e FLASK_ENV=production \
    -e WATCH_DIR=/app/watch \
    --restart unless-stopped \
    $CONTAINER_NAME:latest

echo -e "${GREEN}✓ Container started${NC}"

# Step 8: Display status
echo ""
echo -e "${GREEN}=============================================="
echo "✅ Deployment Complete!"
echo "=============================================${NC}"
echo ""
echo "Dashboard: http://localhost:$PORT"
echo "Logs: docker logs -f $CONTAINER_NAME"
echo "Stop: docker stop $CONTAINER_NAME"
echo "Restart: docker restart $CONTAINER_NAME"
echo ""
echo -e "${YELLOW}📝 Next Steps:${NC}"
echo "1. Copy your Satisfactory save file to: $WATCH_DIR"
echo "2. Open the dashboard in your browser"
echo "3. The app will automatically detect and process the save file"
echo ""
echo -e "${BLUE}Monitoring:${NC}"
docker logs -f $CONTAINER_NAME &
LOGS_PID=$!

# Show some initial logs
sleep 2
echo ""
echo -e "${BLUE}Container Status:${NC}"
docker ps --filter "name=$CONTAINER_NAME" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
