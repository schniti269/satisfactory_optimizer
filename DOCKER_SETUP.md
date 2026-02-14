# Docker Setup & Deployment Guide

## Overview

The Satisfactory Optimizer is now fully containerized and ready for deployment on Proxmox or any Docker-compatible system.

## What's Included

✅ **Dockerfile** - Container definition with Python 3.11 and graphviz
✅ **docker-compose.yml** - Easy multi-container orchestration
✅ **File Watcher** - Automatic detection and processing of new .sav files
✅ **Deployment Scripts** - One-click setup for Proxmox
✅ **Volume Mounts** - Persistent data and watched directories

## Quick Start

### Option 1: Docker Compose (Recommended)

```bash
# Clone the repo
git clone https://github.com/schniti269/satisfactory_optimizer.git
cd satisfactory_optimizer

# Start the service
docker-compose up -d

# View logs
docker-compose logs -f
```

Access the dashboard at `http://localhost:5000`

### Option 2: Direct Docker Run

```bash
# Build the image
docker build -t satisfactory-optimizer .

# Run the container
docker run -d \
  --name satisfactory-optimizer \
  -p 5000:5000 \
  -v ./watch:/app/watch:ro \
  -v ./data:/app/webapp \
  satisfactory-optimizer:latest

# View logs
docker logs -f satisfactory-optimizer
```

## File Watching Setup

The app automatically watches the `/app/watch` directory for new `.sav` files.

### Mount Your Save Directory

**Option A: Using docker-compose.yml**

Edit `docker-compose.yml`:
```yaml
services:
  satisfactory-optimizer:
    volumes:
      - /path/to/saves:/app/watch:ro
      - ./data:/app/webapp
```

**Option B: Using docker run**

```bash
docker run -d \
  -v /path/to/satisfactory/saves:/app/watch:ro \
  -p 5000:5000 \
  satisfactory-optimizer
```

### Copy Save Files

The app watches for new `.sav` files:

```bash
# Copy your latest save
cp /path/to/your/save.sav /path/to/watch/

# Or create a symlink
ln -s /path/to/satisfactory/saves/latest.sav /app/watch/
```

When a new save file appears, the app automatically:
1. Detects the file
2. Parses the save data
3. Analyzes production chains
4. Detects issues
5. Updates the dashboard

## Proxmox Deployment

### Using the Deployment Script

#### Linux/Bash:
```bash
chmod +x deploy-proxmox.sh
./deploy-proxmox.sh
```

#### Windows PowerShell:
```powershell
deploy-proxmox.bat
```

The script will:
1. Clone the repository
2. Create necessary directories
3. Build the Docker image
4. Start the container
5. Display connection info

### Manual Proxmox Setup

1. **Create an LXC Container** with Docker support:
   ```bash
   # In Proxmox node
   pct create 100 local:vztmpl/debian-12-standard_12.2-1_amd64.tar.zst \
     --hostname satisfactory-optimizer \
     --net0 name=eth0,bridge=vmbr0 \
     --memory 2048 \
     --cores 4
   ```

2. **Install Docker**:
   ```bash
   pct exec 100 -- apt-get update
   pct exec 100 -- apt-get install -y docker.io docker-compose
   ```

3. **Deploy the app**:
   ```bash
   pct exec 100 -- git clone https://github.com/schniti269/satisfactory_optimizer.git
   pct exec 100 -- cd satisfactory_optimizer && docker-compose up -d
   ```

4. **Mount Satisfactory Saves**:
   - Use Proxmox's volume mount feature
   - Or use NFS/SMB to share the save directory

## Volume Structure

```
container:/app
├── watch/           # Read-only mounted save directory
│   └── latest.sav   # Your Satisfactory save file
├── webapp/          # Persisted application data
│   ├── feedback.db  # Issue tracking database
│   └── templates/   # HTML templates
└── ...
```

## Environment Variables

Set these when running the container:

```bash
# Flask environment
FLASK_ENV=production

# Directory to watch for save files
WATCH_DIR=/app/watch

# Flask debug (don't set for production)
# FLASK_DEBUG=0
```

## Persistent Data

The app stores data in the `/app/webapp` directory. Use a named volume or bind mount to persist it:

```yaml
# docker-compose.yml
volumes:
  - satisfactory-data:/app/webapp
```

Or:

```bash
docker run -v /path/to/data:/app/webapp ...
```

## Monitoring

### View Logs

```bash
docker logs -f satisfactory-optimizer
```

Output shows:
```
[Watcher] Started monitoring: /app/watch
[Watcher] Detected new save file: /app/watch/latest.sav
[Watcher] Successfully loaded: 15 issues found
[Watcher] Graph: 423 nodes, 892 edges
```

### Check Container Status

```bash
docker ps --filter "name=satisfactory-optimizer"
docker stats satisfactory-optimizer
```

## Troubleshooting

### File watcher not detecting saves

1. Verify the watch directory exists and is mounted:
   ```bash
   docker exec satisfactory-optimizer ls -la /app/watch
   ```

2. Check permissions (should be readable):
   ```bash
   docker exec satisfactory-optimizer stat /app/watch
   ```

3. Ensure watchdog is installed:
   ```bash
   docker exec satisfactory-optimizer pip show watchdog
   ```

### Dashboard not loading

1. Check if Flask is running:
   ```bash
   docker logs satisfactory-optimizer | tail -20
   ```

2. Test the endpoint:
   ```bash
   curl http://localhost:5000
   ```

### Port already in use

Change the port in docker-compose.yml:
```yaml
ports:
  - "8080:5000"  # Use 8080 instead of 5000
```

Then access at `http://localhost:8080`

## Performance Tuning

### Memory Limits
```yaml
services:
  satisfactory-optimizer:
    deploy:
      resources:
        limits:
          memory: 2G
        reservations:
          memory: 1G
```

### CPU Limits
```yaml
services:
  satisfactory-optimizer:
    deploy:
      resources:
        limits:
          cpus: '2'
```

## Updating

Pull the latest changes and redeploy:

```bash
cd satisfactory_optimizer
git pull origin master
docker-compose down
docker-compose up -d --build
```

## Backup

Backup your issue database and data:

```bash
# Backup data directory
docker run --rm -v satisfactory-data:/data -v $(pwd):/backup \
  busybox tar czf /backup/satisfactory-backup.tar.gz -C / data

# Restore
docker run --rm -v satisfactory-data:/data -v $(pwd):/backup \
  busybox tar xzf /backup/satisfactory-backup.tar.gz
```

## Network Configuration

### Accessing from Other Machines

```bash
# If running on Proxmox node with IP 192.168.1.100
# Access from another machine: http://192.168.1.100:5000
```

### Using a Reverse Proxy (Nginx)

```nginx
server {
    listen 80;
    server_name satisfactory.example.com;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Security Notes

- File watching directory mounted read-only (`:ro`)
- Flask debug mode disabled in production
- Database file should be backed up regularly
- Consider using Docker secrets for sensitive data

## Support

For issues or questions:
1. Check the logs: `docker logs satisfactory-optimizer`
2. Review the README: `cat README.md`
3. File an issue: https://github.com/schniti269/satisfactory_optimizer/issues
