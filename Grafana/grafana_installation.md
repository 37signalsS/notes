# Установка и Настройка Grafana

## Способ 1: Установка через пакетный менеджер (YUM/APT)

Это самый простой способ установить Grafana на выделенный сервер или виртуальную машину. Grafana Labs поддерживает официальные репозитории для DEB- (Debian/Ubuntu) и RPM-совместимых (CentOS/RHEL/Fedora) операционных систем.

### Установка в RPM-based системах (CentOS/RHEL)

1.  **Добавьте репозиторий Grafana.**
    Создайте файл `/etc/yum.repos.d/grafana.repo` со следующим содержимым:

    ```repo
    [grafana]
    name=grafana
    baseurl=https://rpm.grafana.com
    repo_gpgcheck=1
    enabled=1
    gpgcheck=1
    gpgkey=https://rpm.grafana.com/gpg.key
    sslverify=1
    sslcacert=/etc/pki/tls/certs/ca-bundle.crt
    ```

2.  **Установите Grafana.**

    ```bash
    sudo yum install -y grafana
    ```

3.  **Запустите сервис Grafana.**

    ```bash
    sudo systemctl daemon-reload
    sudo systemctl start grafana-server
    sudo systemctl enable grafana-server.service
    ```

### Проверка работы

По умолчанию Grafana слушает порт `3000`. Вы можете проверить, что сервис запущен, с помощью `curl`:

```bash
curl -IL http://localhost:3000/login
```

Вы должны получить ответ `HTTP/1.1 200 OK`. После этого можно заходить в веб-интерфейс по адресу `http://<ваш_ip>:3000` (логин/пароль по умолчанию: `admin`/`admin`).

---

## Способ 2: Установка с помощью Docker Compose

Этот способ идеально подходит для быстрого развертывания Grafana вместе с другими компонентами, такими как Prometheus, в изолированном окружении.

### Структура проекта

Рекомендуется следующая структура каталогов:
```
monitoring/
├── docker-compose.yml
├── .env
├── prometheus/
│   └── prometheus.yml
└── grafana/
    └── provisioning/
        └── datasources/
            └── datasources.yaml
```

### Конфигурация Docker Compose

Пример файла `docker-compose.yml`, который запускает Grafana и Prometheus:

```yaml
# monitoring/docker-compose.yml
version: '3.8'

services:
  prometheus:
    image: prom/prometheus:v2.47.0 # Рекомендуется фиксировать версию
    container_name: prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
    volumes:
      - ./prometheus:/etc/prometheus
      - prom_data:/prometheus
    ports:
      - "9090:9090"
    restart: unless-stopped

  grafana:
    image: grafana/grafana:10.4.2 # Рекомендуется фиксировать версию
    container_name: grafana
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"
    restart: unless-stopped
    depends_on:
      - prometheus

volumes:
  prom_data:
  grafana_data:
```

### Автоматическая настройка (Provisioning)

Grafana может быть автоматически сконфигурирована при старте. В данном примере мы настроим источник данных Prometheus.

Создайте файл `grafana/provisioning/datasources/datasources.yaml`:
```yaml
# monitoring/grafana/provisioning/datasources/datasources.yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090 # Обращение к Prometheus по имени сервиса в Docker-сети
    isDefault: true
    editable: false
```

Подробнее о провижининге см. в заметке [[../grafana_provisioning.md]].

### Запуск и доступ

1.  Запустите стек: `docker-compose up -d`
2.  **Prometheus** будет доступен по `http://localhost:9090`.
3.  **Grafana** будет доступна по `http://localhost:3000` (логин/пароль: `admin`/`admin`). Источник данных Prometheus уже будет настроен.

---

## Способ 3: Установка в Kubernetes с помощью Helm

Helm — это менеджер пакетов для Kubernetes, который позволяет легко устанавливать и управлять сложными приложениями, такими как Grafana. Это предпочтительный способ установки в кластерной среде.

### 1. Подключение репозитория Helm

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
```

### 2. Настройка `values.yaml`

Перед установкой рекомендуется создать свой файл `values.yaml` для переопределения стандартных настроек.

Пример базового `values.yaml`:
```yaml
# values.yaml
persistence:
  enabled: true
  type: pvc
  size: 5Gi

admin:
  user: admin
  password: StrongPassword123! # Обязательно смените пароль!

ingress:
  enabled: true
  ingressClassName: nginx
  hosts:
    - host: grafana.your-domain.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - hosts:
        - grafana.your-domain.com
      secretName: grafana-tls

grafana.ini:
  server:
    root_url: "https://grafana.your-domain.com"
```
*   **`persistence`**: Включает сохранение данных Grafana (дашборды, пользователи) с помощью PersistentVolumeClaim (PVC).
*   **`admin`**: Задает учетные данные администратора.
*   **`ingress`**: Настраивает доступ к Grafana извне кластера через Ingress-контроллер.
*   **`grafana.ini`**: Позволяет переопределять любые настройки из файла `grafana.ini`.

### 3. Установка чарта

```bash
helm install grafana grafana/grafana \
  -f values.yaml \
  --namespace monitoring \
  --create-namespace \
  --wait \
  --atomic
```

### 4. Дополнительные параметры конфигурации

Helm-чарт позволяет гибко настраивать множество параметров:

*   **Провижининг дашбордов**: Автоматическая загрузка дашбордов из ConfigMaps или из библиотеки Grafana.
*   **Image Renderer**: Включение компонента для создания снимков графиков для алертов.
*   **Сторонние плагины**: Автоматическая установка плагинов при старте.

Для более подробной информации обратитесь к документации Helm-чарта и заметке [[../grafana_provisioning.md]].

### 5. Проверка установки

```bash
# Проверить статус пода
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana

# Проверить статус Ingress
kubectl get ingress -n monitoring -l app.kubernetes.io/name=grafana
```

После успешного развертывания Grafana будет доступна по адресу, указанному в `ingress.hosts`.

---
**Связанные темы:**
*   [[grafana_overview.md]]
*   [[grafana_provisioning.md]]
*   [[grafana_dashboards.md]]
*   [[high_availability.md]]
