## Интеграция с Kubernetes

Для конвертации файлов [docker-compose](../Docker_compose/docker_compose.md) в манифесты Kubernetes используйте инструмент **`kompose`**. Он анализирует `docker-compose.yml` и генерирует соответствующие ресурсы Kubernetes (Deployments, Services и т.д.).

### Что такое Kompose?

`kompose` — это инструмент командной строки, разработанный для помощи разработчикам, использующим Docker Compose, перейти на Kubernetes. Он позволяет легко преобразовывать приложения, определенные в `docker-compose.yml`, в объекты Kubernetes.

### Как это работает?

`kompose` считывает файл `docker-compose.yml` и генерирует на его основе стандартные Kubernetes-манифесты (YAML-файлы). Эти манифесты затем могут быть применены к кластеру Kubernetes.

**Пример использования:**

1.  **Установка Kompose:**
    (Инструкции по установке зависят от операционной системы и могут быть найдены на официальном сайте `kompose`).

2.  **Конвертация `docker-compose.yml`:**
    Предположим, у вас есть файл `docker-compose.yml` в текущей директории:
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
    Для конвертации выполните:
    ```bash
    kompose convert
    ```
    Эта команда сгенерирует файлы `web-deployment.yaml`, `web-service.yaml`, `app-deployment.yaml`, `app-service.yaml` и т.д., которые соответствуют вашим сервисам из Docker Compose.

3.  **Применение к кластеру Kubernetes:**
    После генерации манифестов их можно применить к кластеру Kubernetes:
    ```bash
    kubectl apply -f .
    ```
