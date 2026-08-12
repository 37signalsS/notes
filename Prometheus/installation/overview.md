# Установка Prometheus: обзор

## Определения

**Установка Prometheus** — процесс развертывания и настройки компонентов экосистемы мониторинга. Полная архитектура системы описана в документе **[Обзор Prometheus](../overview.md)**.

Экосистема включает следующие ключевые компоненты:

*   **Prometheus Server**: центральный узел для сбора, хранения и обработки метрик в формате временных рядов (TSDB). Подробно: **[Установка Prometheus Server](./prometheus_server_installation.md)**.
*   **Node Exporter**: агент для сбора метрик хостовой операционной системы (CPU, RAM, диск, сеть). Подробно: **[Установка Node Exporter](./node_exporter_installation.md)**.
*   **Blackbox Exporter**: компонент для проверки доступности эндпоинтов по протоколам HTTP, HTTPS, TCP, ICMP и DNS. Подробно: **[Blackbox Exporter: установка](../Exporters/blackbox/blackbox_exporter_installation_and_setup.md)**.
*   **Alertmanager**: обработка оповещений — дедупликация, группировка и маршрутизация уведомлений. Подробно: **[Установка Alertmanager](./alertmanager_installation.md)**.
*   **Pushgateway**: шлюз для приема метрик от кратковременных или пакетных (batch) заданий. Подробно: **[Установка Pushgateway](./pushgateway_installation.md)**.

## Основные концепции

### Способы установки

| Способ | Описание | Сценарий использования |
| :--- | :--- | :--- |
| **Бинарные файлы** | Ручная загрузка с GitHub, настройка systemd | Production-серверы, максимальный контроль |
| **Пакеты APT/YUM** | Установка через стандартные репозитории ОС | Быстрое развертывание, автоматическое обновление |
| **Homebrew (macOS)** | Установка через менеджер пакетов macOS | Локальная разработка и тестирование |
| **Docker / Podman** | Запуск в контейнерах | Изолированные среды, микросервисы, тестирование |
| **Ansible** | Автоматизированное развертывание через роли | Управление парком серверов (IaC) |
| **Helm / Operator** | Установка в Kubernetes | Облачные среды, автоматизация жизненного цикла |
| **Windows MSI** | Установка через MSI-инсталлеры или Chocolatey | Мониторинг инфраструктуры на базе Windows |

### Принцип установки (бинарные файлы)

1.  **Создание пользователя**: Для изоляции процессов создается системный пользователь (например, `prometheus`) без оболочки (`nologin`) и домашней директории.
2.  **Размещение бинарных файлов**: Исполняемые файлы помещаются в `/usr/local/bin/` для обеспечения глобального доступа.
3.  **Конфигурация и хранилище**:
    *   Конфигурационные файлы: `/etc/prometheus/`
    *   Данные TSDB (база данных): `/var/lib/prometheus/`
4.  **Настройка systemd**: Создание unit-файла в `/etc/systemd/system/` для управления жизненным циклом сервиса.
5.  **Hardening (Усиление безопасности)**: При использовании systemd рекомендуется ограничивать права процесса:
    *   `NoNewPrivileges=true`
    *   `ProtectSystem=full`
    *   `DeviceAllow=/dev/null`

## Практические сценарии

### Быстрый старт (Debian/Ubuntu)

Минимальная настройка для локального тестирования:

```bash
# Установка сервера и базового экспортера
sudo apt update && sudo apt install -y prometheus prometheus-node-exporter

# Проверка статуса сервиса
systemctl status prometheus
# → Active: active (running) ...

# Проверка доступности
curl -I http://localhost:9090/graph    # Web UI Prometheus
curl -I http://localhost:9100/metrics  # Метрики Node Exporter
```

> **Подробное руководство:** [Установка через APT](./with_apt.md).

### Установка на macOS (Homebrew)

Подходит для быстрой настройки среды разработки:

```bash
# Установка Prometheus
brew install prometheus

# Запуск сервиса
brew services start prometheus

# Проверка версии
prometheus --version
# → prometheus, version 3.x.x ...
```

### Запуск через Docker или Podman

Универсальный способ для изолированного запуска:

```bash
# Запуск контейнера с монтированием конфигурации
docker run -d \
  --name prometheus \
  -p 9090:9090 \
  -v /path/to/prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus:latest

# Проверка логов
docker logs prometheus
```

### Автоматизация через Ansible

Для массового развертывания рекомендуется использовать роли из коллекции `prometheus.prometheus`:

```yaml
- hosts: monitoring
  become: yes
  roles:
    - prometheus.prometheus.prometheus
    - prometheus.prometheus.node_exporter
```

### Развертывание в Kubernetes

В Kubernetes-кластерах стандартом является использование Helm-чарта `kube-prometheus-stack`, который автоматизирует управление всем стеком через оператора.

Подробные инструкции и сценарии: **[Установка через Helm (kube-prometheus-stack)](../kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/online_installation.md)**.

> **См. также:** **[Обзор kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/overview.md)**.

## Дополнительная информация

### Проверка конфигурации

Всегда проверяйте синтаксис файлов конфигурации перед перезапуском:

*   **Prometheus**: `promtool check config /etc/prometheus/prometheus.yml`
*   **Alertmanager**: `amtool check-config /etc/alertmanager/alertmanager.yml`

Подробнее: **[promtool и лучшие практики](../promtool_and_best_practices.md)**.

### Установка на Windows

Для мониторинга Windows-хостов обычно используется `windows_exporter`, но сам сервер Prometheus также может быть запущен как сервис:
1.  **Бинарный файл**: Скачивание `.exe` с официального сайта.
2.  **Chocolatey**: `choco install prometheus`.
3.  **Scoop**: `scoop install prometheus`.

### См. также
*   **[Архитектура Prometheus](../overview.md)**
*   **[Безопасность Prometheus](../security.md)**
*   **[Масштабирование](../scaling/overview.md)**
