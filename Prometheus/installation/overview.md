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

### Надежность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| **Актуальность** | **10** | Соответствует версиям экосистемы на июль 2026 |
| **Полнота** | **9** | Обзорный документ, детали в специализированных файлах |
| **SSoT** | **10** | Центральный индекс методов установки |

### Способы установки

| Способ | Описание | Сценарий использования |
| :--- | :--- | :--- |
| **Бинарные файлы** | Ручная загрузка с GitHub, настройка systemd | Production-серверы, максимальный контроль |
| **Пакеты APT/YUM** | Установка через стандартные репозитории ОС | Быстрое развертывание, автоматическое обновление |
| **Docker / Compose** | Запуск в контейнерах | Изолированные среды, микросервисы, тестирование |
| **Ansible** | Автоматизированное развертывание через роли | Управление парком серверов (IaC) |
| **Helm / Operator** | Установка в Kubernetes | Облачные среды, автоматизация жизненного цикла |

### Принцип установки (бинарные файлы)

1.  **Создание пользователя**: Для изоляции процессов создается отдельный системный пользователь (например, `prometheus`) без прав на вход в систему.
2.  **Размещение бинарных файлов**: Исполняемые файлы помещаются в `/usr/local/bin/` для глобального доступа.
3.  **Конфигурация и хранилище**:
    *   Конфигурационные файлы: `/etc/prometheus/`
    *   Данные TSDB (база данных): `/var/lib/prometheus/`
4.  **Настройка systemd**: Создание unit-файла в `/etc/systemd/system/` для управления жизненным циклом сервиса.

## Практические сценарии

### Быстрый старт (Debian/Ubuntu)

Минимальная настройка для локального тестирования:

```bash
# Установка сервера и базового экспортера
sudo apt update && sudo apt install -y prometheus prometheus-node-exporter

# Проверка доступности
curl -I http://localhost:9090/graph    # Web UI Prometheus
curl -I http://localhost:9100/metrics  # Метрики Node Exporter
```

> **Подробное руководство:** [Установка через APT](./with_apt.md).

### Автоматизация через Ansible

Для массового развертывания рекомендуется использовать проверенные комьюнити-роли (например, из официальной коллекции `prometheus.prometheus`):

```yaml
- hosts: monitoring
  roles:
    - prometheus.prometheus.prometheus
    - prometheus.prometheus.node_exporter
```

### Развертывание в Kubernetes

В K8s-кластерах стандартом является использование Helm-чарта `kube-prometheus-stack`, который включает в себя Prometheus Operator.

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace
```

> **См. также:** **[Обзор kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/overview.md)**.

## Дополнительная информация

### Проверка конфигурации

Перед перезапуском сервисов всегда проверяйте синтаксис файлов конфигурации:

*   **Prometheus**: `promtool check config /etc/prometheus/prometheus.yml`
*   **Alertmanager**: `amtool check-config /etc/alertmanager/alertmanager.yml`

Подробнее: **[promtool и лучшие практики](../promtool_and_best_practices.md)**.

### Актуальные версии (июль 2026)

| Компонент | Версия | Статус |
| :--- | :--- | :--- |
| **Prometheus Server** | `3.13.2` | Stable (LTS) |
| **Node Exporter** | `1.12.1` | Stable |
| **Blackbox Exporter** | `0.28.0` | Stable |
| **Alertmanager** | `0.33.1` | Stable |
| **Pushgateway** | `1.11.3` | Stable |

> **Важно:** Всегда проверяйте актуальные релизы в [официальном репозитории](https://github.com/prometheus).

### См. также
*   **[Архитектура Prometheus](../overview.md)**
*   **[Безопасность Prometheus](../security.md)**
*   **[Масштабирование](../scaling/overview.md)**
