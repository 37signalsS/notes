# Установка Prometheus через APT

## Определения

**Установка через APT** — метод развертывания Prometheus и его компонентов на дистрибутивах Linux на базе Debian (включая Ubuntu) с использованием стандартного пакетного менеджера `apt`.

*   **Prometheus Server**: основной сервис сбора и хранения метрик. В репозиториях поставляется как пакет `prometheus`.
*   **Node Exporter**: агент для мониторинга ресурсов хоста. Поставляется как пакет `prometheus-node-exporter`.
*   **PPA (Personal Package Archive)**: сторонний репозиторий для Ubuntu, используемый для получения свежих версий ПО, недоступных в официальных репозиториях.

## Основные концепции

### Преимущества пакетной установки

1.  **Автоматизация**: Пакеты автоматически настраивают `systemd` unit-файлы, создают системного пользователя `prometheus` и настраивают ротацию логов через `logrotate`.
2.  **Безопасность**: Обновления безопасности интегрированы в общий цикл обновления системы (`apt upgrade`).
3.  **Стандартная иерархия путей**:
    *   **Конфигурация**: `/etc/prometheus/prometheus.yml`
    *   **Флаги запуска**: `/etc/default/prometheus`
    *   **Данные (TSDB)**: `/var/lib/prometheus/`
    *   **Исполняемые файлы**: `/usr/bin/prometheus`

### Особенности управления версиями

Официальные репозитории Debian и Ubuntu часто содержат устаревшие версии (например, ветку 2.x, когда актуальна 3.x).
*   **Фиксация версии**: Чтобы избежать нежелательного обновления при `apt upgrade`, используйте команду `apt-mark hold`.
*   **Конфликты конфигурации**: При обновлении пакета APT может спросить, оставить ли ваш `prometheus.yml` или заменить его версией из пакета. Всегда выбирайте сохранение текущей версии (`N` или `O`).

## Практические сценарии

### Сценарий 1: Базовая установка из официальных репозиториев

Подходит для стабильных систем, где приоритетом является совместимость, а не новые функции.

```bash
# 1. Обновление локального индекса пакетов
sudo apt update

# 2. Установка сервера и базового экспортера
sudo apt install -y prometheus prometheus-node-exporter
# → [OK] Installed prometheus, prometheus-node-exporter

# 3. Проверка автоматического запуска сервисов
sudo systemctl is-active prometheus
# → active
```

### Сценарий 2: Установка свежих версий через PPA (Ubuntu)

Рекомендуется для получения Prometheus 3.0+ на старых версиях ОС.

```bash
# 1. Добавление репозитория сообщества
sudo add-apt-repository ppa:prometheus-community/ppa -y

# 2. Обновление и установка
sudo apt update && sudo apt install -y prometheus
# → [OK] Upgraded to latest community version

# 3. Проверка версии
prometheus --version
# → prometheus, version 3.x.x ...
```

### Сценарий 3: Фиксация версии (Pinning)

Предотвращает автоматическое обновление Prometheus, которое может привести к несовместимости конфигурации.

```bash
# Фиксация текущей версии
sudo apt-mark hold prometheus
# → prometheus set on hold.

# Снятие фиксации для планового обновления
sudo apt-mark unhold prometheus
# → prometheus placed on hold.
```

### Сценарий 4: Кастомизация параметров запуска

Редактирование лимитов памяти, времени хранения (retention) и внешних URL выполняется через файл `/etc/default/prometheus`.

```bash
# Откройте файл для редактирования
sudo nano /etc/default/prometheus

# Пример настройки retention на 30 дней и включение API управления
ARGS="--storage.tsdb.retention.time=30d --web.enable-lifecycle"

# Применение изменений
sudo systemctl restart prometheus
```

### Сценарий 5: Настройка межсетевого экрана (UFW)

```bash
# Разрешить доступ к UI (порт 9090)
sudo ufw allow 9090/tcp comment 'Prometheus UI'

# Разрешить сбор метрик сервером с агента (порт 9100)
sudo ufw allow from <IP_SERVER> to any port 9100 proto tcp comment 'Node Exporter'
# → Rules updated
```

## Дополнительная информация

### Диагностика и отладка

При сбое запуска (`code=exited, status=1`) используйте следующие инструменты:

1.  **Проверка синтаксиса YAML**:
    ```bash
    promtool check config /etc/prometheus/prometheus.yml
    # → SUCCESS: /etc/prometheus/prometheus.yml is valid
    ```
2.  **Анализ логов через journald**:
    ```bash
    # Просмотр последних 50 строк лога
    sudo journalctl -u prometheus -n 50 --no-pager
    ```
3.  **Проверка прав доступа**:
    Убедитесь, что директория данных принадлежит пользователю `prometheus`:
    ```bash
    ls -ld /var/lib/prometheus
    # → drwxr-xr-x prometheus prometheus ...
    ```

### См. также
*   **[Установка Prometheus: обзор](./overview.md)** — архитектурные отличия методов установки.
*   **[Управление службами через systemctl](../../Linux/Core/systemd/service_management.md)** — команды управления демонами.
*   **[Конфигурация Prometheus](../configuration.md)** — глубокая настройка правил и скрейпинга.
*   **[Node Exporter: установка](./node_exporter_installation.md)** — детальная настройка системного агента.
