# Prometheus Installation: Overview

## Definitions

**Prometheus** — система мониторинга и оповещения с открытым исходным кодом. Для полноценной работы требуются дополнительные компоненты. Полная архитектура — [Prometheus overview](../overview.md).

* **Prometheus Server**: сбор, хранение и обработка метрик в формате временных рядов (TSDB). Подробно: [Prometheus Server installation](./prometheus_server_installation.md).
* **Node Exporter**: сбор метрик хостовой системы (CPU, RAM, диск, сеть). Подробно: [Node Exporter installation](./node_exporter_installation.md).
* **Blackbox Exporter**: проверка доступности эндпоинтов (HTTP, HTTPS, TCP, ICMP, DNS). Подробно: [Blackbox Exporter installation](./Blackbox_Exporter/blackbox_exporter_installation.md).
* **Alertmanager**: обработка алертов — дедупликация, группировка, маршрутизация. Подробно: [Alertmanager installation](./alertmanager_installation.md).
* **Pushgateway**: отправка метрик кратковременными и batch-заданиями. Подробно: [Pushgateway installation](./pushgateway_installation.md).

> **См. также:** [Архитектура Prometheus](../overview.md), [Exporters](../Exporters/overview.md).

## Basic Concepts

### Способы установки

| Способ | Описание | Сценарий использования |
|---|---|---|
| **Бинарные файлы** | Ручная загрузка с GitHub, настройка systemd | Production-серверы, полный контроль |
| **Пакеты APT** | Установка через `apt install` | Debian/Ubuntu, быстрое развертывание |
| **Docker** | Запуск в контейнерах | Изолированные среды, тестирование |
| **Helm** | Установка в Kubernetes | K8s-кластеры, GitOps |

### Принцип установки (бинарные файлы)

1. **Создание пользователя**: Для изоляции процессов и повышения безопасности для каждого компонента создается отдельный системный пользователь без прав на вход в систему. Исключением является `Node Exporter`, которому для сбора некоторых метрик может потребоваться `root`-доступ.

2. **Загрузка и размещение бинарных файлов**: Архив с последней стабильной версией компонента загружается с официального репозитория на GitHub, распаковывается, а исполняемый файл помещается в директорию `/usr/local/bin/`.

3. **Создание конфигурации**: Создаются необходимые каталоги (например, `/etc/<component>`, `/var/lib/<component>`) и файлы конфигурации для компонента.

4. **Настройка `systemd` сервиса**: Для управления процессом (автозапуск, перезапуск) создается unit-файл в `/etc/systemd/system/`. Параметры запуска выносятся в отдельный environment-файл в `/etc/sysconfig/` (для CentOS/RHEL) или интегрируются напрямую в unit-файл.

### Управление через `systemd`

После создания unit-файла для каждого компонента используются стандартные команды `systemctl`:

* `systemctl daemon-reload`: Перечитать конфигурацию `systemd`.
* `systemctl start <service>`: Запустить сервис.
* `systemctl enable <service>`: Включить автозапуск сервиса при старте системы.
* `systemctl status <service>`: Проверить статус сервиса.
* `systemctl stop <service>`: Остановить сервис.
* `systemctl restart <service>`: Перезапустить сервис.
* `systemctl reload <service>`: Перезагрузить конфигурацию сервиса без его полной остановки (поддерживается не всеми сервисами).

## Practical Scenarios

### Быстрый старт

**Минимальная установка для тестирования:**

```bash
# Установка Prometheus и Node Exporter через APT (Debian/Ubuntu)
sudo apt update
sudo apt install prometheus prometheus-node-exporter

# Проверка
curl http://localhost:9090/graph  # Prometheus UI
curl http://localhost:9100/metrics  # Node Exporter metrics
```

> **Подробное руководство:** [Установка через APT](./with_apt.md).

### Production-установка

**Рекомендуемый подход для production-серверов:**

1. Используйте последние стабильные версии (проверьте на [GitHub Releases](https://github.com/prometheus))
2. Настройте безопасность (пользователи, firewall, TLS)
3. Настройте мониторинг самого Prometheus (self-monitoring)
4. Используйте внешнее хранилище для долгосрочных данных

> **См. также:** [Безопасность](#рекомендации-по-безопасности), [Scaling](../scaling/overview.md).

### Установка в Kubernetes

**Для K8s-кластеров используйте Helm:**

```bash
# kube-prometheus-stack (полный стек)
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace
```

> **Подробное руководство:** [Установка через Helm](./with_helm_chart.md), [Kube-Prometheus-Stack](../kubernetes/Kube_Prometheus_Stack_Helm/overview.md).

## Additional Information

### Проверка конфигурации компонентов

Перед применением изменений в конфигурации Prometheus и Alertmanager всегда проверяйте синтаксис с помощью утилит `promtool` и `amtool`. Это помогает избежать ошибок, которые могут привести к остановке сбора метрик или обработки оповещений.

* **Prometheus**:

    ```bash
    promtool check config /etc/prometheus/prometheus.yml
    ```

    Подробнее об утилите `promtool` можно прочитать в заметке [promtool и лучшие практики](../promtool_and_best_practices.md).

* **Alertmanager**:

    ```bash
    amtool check-config /etc/alertmanager/alertmanager.yml
    ```

### Рекомендации по безопасности

При развертывании компонентов Prometheus следуйте основным принципам безопасности:

* **Пользователи**: Запускайте каждый компонент от непривилегированного пользователя. Это снижает потенциальный ущерб в случае эксплуатации уязвимостей.
* **Сетевые доступы**: Настраивайте файрвол для ограничения доступа к веб-интерфейсам и API компонентов только с доверенных IP-адресов.
* **TLS**: Для защиты трафика между компонентами и при доступе пользователей используйте TLS-шифрование, например, с помощью обратного прокси-сервера (Nginx, Traefik).

### Актуальные версии

| Компонент | Версия |
|---|---|
| **Prometheus** | 3.11.1 |
| **Node Exporter** | 1.11.1 |
| **Blackbox Exporter** | 0.28.0 |
| **Alertmanager** | 0.32.0 |
| **Pushgateway** | 1.11.2 |

> **Важно:** Всегда проверяйте [официальные репозитории GitHub](https://github.com/prometheus) для получения последних стабильных версий.
