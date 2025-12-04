# Сбор метрик для Prometheus

**Метрики Docker Engine**

Сам Docker может отдавать метрики о своей работе (количество контейнеров, образов и т.д.).

- **Настройка:** Включите `metrics-addr` в файле `/etc/docker/daemon.json`.

  ```json
  {
    "metrics-addr": "0.0.0.0:9323",
    "experimental": true
  }
  ```
- **Назначение:** Мониторинг состояния самого Docker демона.

**Метрики контейнеров (cAdvisor)**

Для сбора детальных метрик производительности *каждого* контейнера используется **cAdvisor (Container Advisor)** от Google. Это стандарт де-факто.

- **Назначение:** Собирает, агрегирует и отдает в формате Prometheus детальную информацию о потреблении CPU, памяти, сети и диска для всех контейнеров на хосте.
- **Запуск:** cAdvisor запускается как еще один Docker-контейнер.

  ```yaml
  # Пример запуска cAdvisor в docker-compose.yml
  services:
    cadvisor:
      image: gcr.io/cadvisor/cadvisor:v0.53.0
      container_name: cadvisor
      ports:
        - "8080:8080"
      volumes:
        - /:/rootfs:ro
        - /var/run:/var/run:rw
        - /sys:/sys:ro
        - /var/lib/docker/:/var/lib/docker:ro
      restart: unless-stopped
  ```
> **Примечание:** Для получения полной картины мониторинга хоста, `cAdvisor` обычно используется в связке с **`node-exporter`**, который собирает метрики самой хост-системы (CPU, диск, сеть и т.д.).

**Метрики приложений**

Метрики, специфичные для вашего приложения (например, количество обработанных запросов, время ответа API).

- **Принцип работы:** Приложение само отдает метрики по эндпоинту `/metrics` с помощью клиентских библиотек Prometheus.
- **Настройка:** Вам нужно лишь убедиться, что порт для метрик доступен для скрейпера Prometheus.

*   [draganm/missing-container-metrics](https://github.com/draganm/missing-container-metrics)
*   [google/cadvisor](https://github.com/google/cadvisor)
