# Конфигурация Docker Compose

Для развертывания стека используется файл `monitoring/docker-compose.yml` со следующим содержимым:

```yaml
version: '3.7'

services:
  prometheus:
    image: prom/prometheus:v2.53.1 # Используйте актуальную версию
    container_name: prometheus
    volumes:
      - ./prometheus:/etc/prometheus
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/usr/share/prometheus/console_libraries'
      - '--web.console.templates=/usr/share/prometheus/consoles'
    ports:
      - "9090:9090"
    restart: unless-stopped
    networks:
      - monitoring-net

  alertmanager:
    image: prom/alertmanager:v0.27.0 # Используйте актуальную версию
    container_name: alertmanager
    volumes:
      - ./alertmanager:/config
    command:
      - '--config.file=/config/config.yml'
      - '--storage.path=/alertmanager'
    ports:
      - "9093:9093"
    restart: unless-stopped
    networks:
      - monitoring-net

  node-exporter:
    image: prom/node-exporter:v1.8.2 # Используйте актуальную версию
    container_name: node-exporter
    pid: host # Позволяет видеть процессы хоста
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro # Доступ к корневой ФС хоста
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
    ports:
      - "9100:9100"
    restart: unless-stopped
    networks:
      - monitoring-net

  cadvisor:
    image: ghcr.io/cadvisor/cadvisor:v0.56.0 # Используйте актуальную версию
    container_name: cadvisor
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:rw
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
    ports:
      - "8080:8080"
    restart: unless-stopped
    networks:
      - monitoring-net

  grafana:
    image: grafana/grafana:11.1.0 # Используйте актуальную версию
    container_name: grafana
    volumes:
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"
    restart: unless-stopped
    networks:
      - monitoring-net

volumes:
  prometheus_data:
  grafana_data:

networks:
  monitoring-net:
    driver: bridge
```
