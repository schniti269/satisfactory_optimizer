# Satisfactory Factory Optimizer & Analyzer

A comprehensive tool for analyzing Satisfactory game save files, detecting supply chain issues, and optimizing production.

## Features

- **Save File Analysis**: Upload .sav files to analyze factory layout and production
- **Issue Detection**: Identifies bottlenecks, inefficient routing, and production imbalances
- **Supply Chain Visualization**: Interactive graph analysis of production flows
- **Auto File Watching**: Automatically processes save files placed in a mounted directory
- **Dashboard**: Real-time factory metrics and issue tracking
- **Ticket System**: Create, track, and resolve factory issues

## Quick Start with Docker

### Prerequisites
- Docker and Docker Compose installed

### Running the Container

```bash
docker-compose up -d
```

The dashboard will be available at `http://localhost:5000`

### File Watching Setup

The app watches for new `.sav` files in the `./watch` directory and automatically processes them.

**To use with your Satisfactory server:**

1. Mount your save directory to the container's `/app/watch` volume
2. Create a symlink or copy your latest save file to the watch directory
3. The dashboard will auto-update with the new analysis

Example `docker-compose.yml` override:
```yaml
services:
  satisfactory-optimizer:
    volumes:
      - /mnt/satisfactory/saves:/app/watch:ro
      - ./data:/app/webapp
```

## Local Development

### Requirements
- Python 3.11+
- pip

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Run the App

```bash
python webapp/app.py
```

The dashboard will be available at `http://localhost:5000`

### Run with File Watching

Set the `WATCH_DIR` environment variable:

```bash
WATCH_DIR=./watch python webapp/app.py
```

## Usage

### Web Dashboard

1. Open `http://localhost:5000`
2. Upload a Satisfactory save file (.sav)
3. View the factory analysis and detected issues
4. Use the dashboard to explore production chains and create tickets

### Command Line Tools

Run the optimizer directly:

```bash
python main.py                  # Full optimization with flowchart
python main.py --no-flowchart   # Optimization only
python main.py --no-alternates  # Exclude alternate recipes
```

## Architecture

- **Flask Web App** (`webapp/app.py`): Main dashboard interface
- **Save Parser** (`save_parser.py`): Parses .sav binary format
- **Graph Analyzer** (`graph_analyzer.py`): Supply chain analysis
- **District Analyzer** (`district_analyzer.py`): Spatial analysis
- **Feedback DB** (`feedback_db.py`): Issue tracking and tickets
- **File Watcher**: Auto-detection of new save files

## Deployment on Proxmox

### Docker Setup

```bash
# Build and run the container
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the container
docker-compose down
```

### Volume Mounting

Mount your Satisfactory save directory to `/app/watch`:

```bash
docker run -v /mnt/satisfactory/saves:/app/watch:ro \
           -v satisfactory-data:/app/webapp \
           -p 5000:5000 \
           satisfactory-optimizer
```

### Proxmox LXC Setup

If using an LXC container in Proxmox:

1. Create an LXC with Docker
2. Mount the Satisfactory save directory
3. Pull and run the docker image
4. Access dashboard from Proxmox network

## File Structure

```
.
├── webapp/                    # Flask application
│   ├── app.py               # Main web app
│   ├── save_parser.py       # .sav file parser
│   ├── graph_analyzer.py    # Supply chain analysis
│   ├── district_analyzer.py # Spatial analysis
│   ├── feedback_db.py       # Ticket system
│   ├── templates/           # HTML templates
│   └── static/              # CSS, JS, assets
├── main.py                  # CLI optimizer entry point
├── satisfactory_optimizer.py # Optimization engine
├── satisfactory_data.py     # Game data & recipes
├── satisfactory_flowchart.py # Visualization
├── Dockerfile               # Container definition
├── docker-compose.yml       # Container orchestration
└── requirements.txt         # Python dependencies
```

## Environment Variables

- `FLASK_ENV`: Set to `production` for deployment
- `WATCH_DIR`: Directory to watch for new .sav files (default: `./watch`)

## Troubleshooting

**File watcher not working:**
- Ensure `watchdog` is installed: `pip install watchdog`
- Check `WATCH_DIR` path exists and is writable

**Parse errors:**
- Ensure you're using the correct Satisfactory version (.sav format)
- Check application logs for detailed error messages

**Dashboard not loading:**
- Verify Flask is running: `docker-compose logs`
- Check that port 5000 is not already in use

## License

This project analyzes Satisfactory game saves. Respect all applicable licenses and terms of service.
