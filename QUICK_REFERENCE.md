# Quick Reference - Satisfactory Optimizer

## 🚀 Start the App

### Docker Compose (Recommended)
```bash
docker-compose up -d
# Access: http://localhost:5000
```

### Direct Docker
```bash
docker build -t satisfactory-optimizer .
docker run -d -p 5000:5000 \
  -v ./watch:/app/watch:ro \
  -v ./data:/app/webapp \
  satisfactory-optimizer
```

### Python Local
```bash
pip install -r requirements.txt
python webapp/app.py
```

---

## 📂 File Watching

### Set Watch Directory (docker-compose)
Edit `docker-compose.yml`:
```yaml
volumes:
  - /mnt/satisfactory/saves:/app/watch:ro  # Change this path
  - ./data:/app/webapp
```

### Place Save File
```bash
cp ~/Satisfactory/Saved\ Games/latest.sav ./watch/
```

The app auto-processes it!

---

## 🔍 Monitoring

### View Logs
```bash
docker logs -f satisfactory-optimizer
docker-compose logs -f
```

### Check Container Status
```bash
docker ps --filter "name=satisfactory-optimizer"
docker stats satisfactory-optimizer
```

### Enter Container
```bash
docker exec -it satisfactory-optimizer /bin/bash
docker exec -it satisfactory-optimizer python -c "import watchdog; print(watchdog.__version__)"
```

---

## ⚙️ Container Management

### Stop
```bash
docker stop satisfactory-optimizer
docker-compose down
```

### Restart
```bash
docker restart satisfactory-optimizer
docker-compose restart
```

### Remove
```bash
docker rm satisfactory-optimizer
docker-compose down
```

### Rebuild Image
```bash
docker build --no-cache -t satisfactory-optimizer .
docker-compose up -d --build
```

---

## 💾 Data Management

### Backup Database
```bash
docker cp satisfactory-optimizer:/app/webapp/feedback.db ./backup/
docker-compose exec satisfactory-optimizer cp /app/webapp/feedback.db /app/webapp.backup
```

### Backup All Data
```bash
docker run --rm -v satisfactory-data:/data -v $(pwd):/backup \
  busybox tar czf /backup/backup.tar.gz -C / data
```

### Restore Data
```bash
docker run --rm -v satisfactory-data:/data -v $(pwd):/backup \
  busybox tar xzf /backup/backup.tar.gz
```

---

## 🔧 Troubleshooting

### Port Already in Use
```bash
# Find what's using the port
netstat -ano | findstr :5000        # Windows
lsof -i :5000                       # Linux/Mac

# Change port in docker-compose.yml
ports:
  - "8080:5000"
```

### File Watcher Not Working
```bash
# Check watch directory
docker exec satisfactory-optimizer ls -la /app/watch

# Verify watchdog installed
docker exec satisfactory-optimizer pip show watchdog

# Check permissions
docker exec satisfactory-optimizer stat /app/watch
```

### Dashboard Shows "Upload a Save File"
```bash
# No save loaded yet, either:
# 1. Upload via web: http://localhost:5000/upload
# 2. Copy to watch dir: cp yourfile.sav ./watch/
```

### Save File Not Processing
```bash
# Check logs for errors
docker logs satisfactory-optimizer | grep -i error

# Verify file is valid
file ./watch/yourfile.sav

# Try manual upload to test parsing
```

---

## 📝 Git Operations

### Commit Changes
```bash
git add .
git commit -m "Your message"
git push origin master
```

### View History
```bash
git log --oneline -10
git diff
git status
```

### Pull Latest
```bash
git pull origin master
docker-compose up -d --build
```

---

## 🌐 Network Access

### Local Machine
```
http://localhost:5000
```

### From Another Machine
```
http://<your-ip>:5000
```

### Proxmox LXC
```
http://<lxc-ip>:5000
```

### With Nginx Reverse Proxy
```nginx
server {
    listen 80;
    server_name satisfactory.local;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
    }
}
```

---

## 🔐 Security

### Run in Production Mode
```bash
export FLASK_ENV=production
docker-compose up -d
```

### Restrict Access (iptables)
```bash
iptables -A INPUT -p tcp --dport 5000 -s 192.168.1.0/24 -j ACCEPT
iptables -A INPUT -p tcp --dport 5000 -j DROP
```

### Use Environment Variables
```bash
# Set in docker-compose.yml
environment:
  - FLASK_ENV=production
  - WATCH_DIR=/app/watch
```

---

## 📊 Dashboard Features

### Upload Page
- Drag & drop save file
- Or use file browser
- Max 200MB

### Dashboard
- Factory overview
- Issue list (filterable)
- Production graphs
- District analysis
- Ticket management

### API Endpoints
```
GET  /                     # Redirect to upload/dashboard
GET  /upload              # Upload page
POST /upload              # Upload save file
GET  /dashboard           # View analysis
GET  /api/issues          # Get issues (JSON)
POST /api/feedback        # Submit feedback
GET  /api/tickets         # Get tickets
POST /api/tickets         # Create ticket
```

---

## 🎯 Common Workflows

### First Time Setup
```bash
# Clone repo
git clone https://github.com/schniti269/satisfactory_optimizer.git
cd satisfactory_optimizer

# Start with docker-compose
docker-compose up -d

# Copy your save
cp ~/Satisfactory/Saved\ Games/latest.sav ./watch/

# Open dashboard
open http://localhost:5000
```

### Update to Latest Version
```bash
git pull origin master
docker-compose up -d --build
```

### Backup Before Update
```bash
docker exec satisfactory-optimizer \
  cp /app/webapp/feedback.db /app/webapp/backup.db
git pull origin master
docker-compose up -d --build
```

### Deploy to Proxmox
```bash
# Copy repo to Proxmox
scp -r satisfactory_optimizer user@proxmox:/opt/

# SSH into Proxmox
ssh user@proxmox

# Deploy
cd /opt/satisfactory_optimizer
docker-compose up -d
```

---

## 📈 Performance Tips

### Limit Resources
```yaml
services:
  satisfactory-optimizer:
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '1'
```

### Use Read-Only Mount
```yaml
volumes:
  - ./watch:/app/watch:ro  # ← :ro means read-only
```

### Clean Up Old Data
```bash
docker system prune -a
docker volume prune
```

---

## 🆘 Getting Help

### Check Documentation
- **README.md** - Features and overview
- **DOCKER_SETUP.md** - Detailed Docker guide
- **DEPLOYMENT_SUMMARY.md** - What was done

### View Logs
```bash
docker logs -f satisfactory-optimizer
docker logs --tail 50 satisfactory-optimizer
docker logs --since 5m satisfactory-optimizer
```

### Test the Application
```bash
curl http://localhost:5000
curl http://localhost:5000/dashboard
curl http://localhost:5000/api/issues
```

### Report Issues
https://github.com/schniti269/satisfactory_optimizer/issues

---

**Last Updated:** 2026-02-14
**Version:** Docker with File Watching
