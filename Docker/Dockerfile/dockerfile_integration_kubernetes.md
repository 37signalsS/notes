### Определения

**`kompose`** — это инструмент командной строки, предназначенный для упрощения перехода с [Docker Compose](../Docker_compose/docker_compose.md) на Kubernetes. Он автоматически конвертирует файлы `docker-compose.yml` в ресурсы Kubernetes, такие как Deployments и Services.

### Основные концепции

`kompose` анализирует файл `docker-compose.yml` и на его основе генерирует стандартные манифесты Kubernetes в формате YAML. Эти файлы полностью готовы для применения в кластере, что позволяет быстро развернуть приложение.


### Практические сценарии

#### **1. Установка**

Инструкции по установке `kompose` зависят от операционной системы и доступны на официальном сайте инструмента.

#### **2. Конвертация `docker-compose.yml`**

Предположим, у вас есть следующий файл `docker-compose.yml`:
```yaml
version: '3.8'
services:
  web:
    image: nginx:latest
    ports:
      - "80:80"
  app:
    image: my-app:latest
    ports:
      - "5000:5000"
```

Для конвертации выполните команду:
```bash
kompose convert
```
В результате будут созданы файлы `web-deployment.yaml`, `web-service.yaml`, `app-deployment.yaml` и `app-service.yaml`.

#### **3. Развертывание в Kubernetes**

Сгенерированные манифесты можно применить к кластеру с помощью `kubectl`:
```bash
kubectl apply -f .
```