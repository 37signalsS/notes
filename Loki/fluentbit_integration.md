# Интеграция Fluent Bit с Loki

## 1. Определения

Для ознакомления с базовыми концепциями Loki, обратитесь к основному источнику знаний: **[Обзор Grafana Loki](./loki_overview.md)**.
Для изучения основ конфигурации Fluent Bit: **[Конфигурация Fluent Bit](../Kubernetes/MonitoringLogging/EFK/fluentbit/fluentbit_configuration.md)**.

## 2. Базовые концепции

### Выбор версии Fluent Bit

| Версия | Статус | Рекомендация |
| :--- | :--- | :--- |
| **Fluent Bit v3.x** | ✅ Активно развивается | Рекомендуется для новых развертываний |
| **Fluent Bit v2.x** | ✅ Поддерживается | Стабильная версия для production |
| **grafana/fluent-bit** | ⚠️ Deprecated | Не использовать, переходить на официальный Fluent Bit |

> **Важно:** Официальный Fluent Bit имеет встроенный output-плагин `grafana-loki`, который отлично работает. Избегайте устаревшего образа `grafana/fluent-bit`.

### Ключевая особенность Loki: Уникальность лейблов

В отличие от Elasticsearch, который индексирует практически любые данные, Loki накладывает строгое ограничение: **в один и тот же момент времени нельзя отправлять данные с одинаковым набором лейблов**.

Если несколько агентов Fluent Bit (например, с разных узлов кластера) отправят логи одновременно с идентичным статичным набором меток (например, `job="fluent-bit-k8s"`), Loki вернет ошибку, связанную с нарушением порядка (`out-of-order`).

**Решение** — обеспечить уникальность набора лейблов для каждого потока логов. Это достигается добавлением динамических меток, которые идентифицируют источник лога.

**Неправильный подход (приведет к ошибкам):**
```ini
[OUTPUT]
    Name  loki
    Match *
    Host  loki-gateway.loki.svc.cluster.local
    Port  80
    Labels job=fluent-bit-k8s
```

**Правильный подход (добавление динамических меток):**
```ini
[OUTPUT]
    Name  loki
    Match kube.*
    Host  loki-gateway.loki.svc.cluster.local
    Port  80
    Labels job=fluent-bit-k8s, namespace=$kubernetes['namespace_name'], pod=$kubernetes['pod_name'], container=$kubernetes['container_name'], host=$kubernetes['host']
```

В этом примере метки `namespace`, `pod`, `container` и `host` извлекаются из полей, добавленных фильтром `kubernetes`, и гарантируют уникальность потока логов.

### Сравнение: Fluent Bit vs. Grafana Alloy для Loki

| Критерий | Fluent Bit | Grafana Alloy |
| :--- | :--- | :--- |
| **Статус** | ✅ Активно развивается | ✅ Активно развивается |
| **Специализация** | Логи и метрики | Логи + метрики + трассировки + профили |
| **Конфигурация** | INI/TOML/YAML | River (HCL-подобный) |
| **Интеграция с Loki** | Output-плагин `grafana-loki` | Нативный компонент `loki.write` |
| **Kubernetes** | Фильтр `kubernetes` | `discovery.kubernetes` + `loki.source.kubernetes` |
| **Производительность** | Высокая, низкое потребление | Высокая, немного больше ресурсов |
| **Рекомендация** | Для существующих развертываний | Для новых развертываний |

> **Подробнее:** [Grafana Alloy](../Grafana/grafana_alloy_overview.md) — универсальный агент Grafana Labs.

## 3. Практический сценарий: Настройка Fluent Bit для Loki

Этот сценарий описывает конфигурацию Fluent Bit для сбора логов из Kubernetes и системных файлов с последующей отправкой в Loki.

> **Примечание:** Конфигурация актуальна для Fluent Bit v2.x/v3.x. Для Grafana Alloy см. [loki_stack_setup_guide.md](./loki_stack_setup_guide.md#альтернатива-grafana-alloy).

### Файл конфигурации `fluent-bit.conf`

```ini
[SERVICE]
    # Глобальные настройки
    Flush         5
    Daemon        off
    Log_Level     info
    Parsers_File  parsers.conf
    HTTP_Server   On
    HTTP_Listen   0.0.0.0
    HTTP_Port     2020

[INPUT]
    # Сбор логов из подов Kubernetes
    Name              tail
    Tag               kube.*
    Path              /var/log/containers/*.log
    Parser            docker
    Mem_Buf_Limit     10MB
    Skip_Long_Lines   On

[INPUT]
    # Сбор системных логов
    Name              tail
    Tag               syslog.*
    Path              /var/log/messages,/var/log/secure
    Parser            syslog
    Mem_Buf_Limit     5MB

[FILTER]
    # Обогащение логов Kubernetes метаданными
    Name                kubernetes
    Match               kube.*
    Kube_URL            https://kubernetes.default.svc:443
    Merge_Log           On
    Keep_Log            Off
    K8S-Logging.Parser  On
    K8S-Logging.Exclude On

[FILTER]
    # Добавление статических меток для системных логов
    Name record_modifier
    Match syslog.*
    Record application syslog

[OUTPUT]
    # Отправка логов Kubernetes в Loki
    Name               loki
    Match              kube.*
    Host               loki-gateway.loki.svc.cluster.local # Адрес вашего Loki Gateway
    Port               80
    Labels             job=k8s, namespace=$kubernetes['namespace_name'], pod=$kubernetes['pod_name'], container=$kubernetes['container_name'], host=$kubernetes['host']
    Line_Format        log
    LogLevel           info

[OUTPUT]
    # Отправка системных логов в Loki
    Name               loki
    Match              syslog.*
    Host               loki-gateway.loki.svc.cluster.local
    Port               80
    Labels             job=syslog, host=$hostname, app=$application, file=$filename
    Line_Format        log
    LogLevel           info
```

### Разбор конфигурации

#### `[INPUT]` секции
1.  **Первая секция (`kube.*`)**: Использует плагин `tail` для чтения всех файлов логов контейнеров в `/var/log/containers/`. Применяет парсер `docker` для разбора стандартного формата логов Docker/containerd.
2.  **Вторая секция (`syslog.*`)**: Читает системные логи из `/var/log/messages` и `/var/log/secure`, используя парсер `syslog`.

#### `[FILTER]` секции
1.  **`kubernetes`**: Перехватывает логи с тегом `kube.*` и обогащает их метаданными из Kubernetes API: `pod_name`, `namespace_name`, `labels`, `annotations` и т.д. Эти поля становятся доступны для использования в `[OUTPUT]`.
2.  **`record_modifier`**: Добавляет статическое поле `application: syslog` к системным логам.

#### `[OUTPUT]` секции
Обе секции используют плагин `loki`.
1.  **`kube.*`**:
    -   `Labels`: Динамически создает набор лейблов из полей, добавленных фильтром `kubernetes`. Это обеспечивает уникальность потоков логов. `job=k8s` — статическая метка для удобства фильтрации.
    -   `Line_Format log`: Указывает, что в качестве строки лога должно использоваться содержимое поля `log`.
2.  **`syslog.*`**:
    -   `Labels`: Использует `hostname` (внутренняя переменная Fluent Bit), `application` (добавлено фильтром) и `filename` (внутренняя переменная) для создания уникального набора лейблов.

## 4. Устранение неполадок

### Ошибка: `413 Request Entity Too Large`

Эта ошибка возникает, когда Fluent Bit пытается отправить в Loki батч (пакет) логов, размер которого превышает лимит, установленный на стороне Loki (или на прокси перед ним, например, Nginx Ingress).

**Решения:**

| Решение | Описание | Пример |
| :--- | :--- | :--- |
| **Увеличить лимит в Loki** | Параметр `max_body_size` в конфигурации Loki | `server.http_listen_max_body_size: 10MB` |
| **Увеличить лимит в Ingress** | Аннотация для Nginx Ingress | `nginx.ingress.kubernetes.io/proxy-body-size: "10m"` |
| **Уменьшить батч в Fluent Bit** | Параметры `Flush` и `Mem_Buf_Limit` | `Flush 1`, `Mem_Buf_Limit 5MB` |

**Пример настройки Ingress для Loki:**
```yaml
# Ingress для Loki Gateway
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: loki-gateway
  namespace: logging
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "600"
spec:
  rules:
    - host: loki.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: loki-gateway
                port:
                  number: 80
```

## 4. Дополнительные ресурсы

| Ресурс | Описание |
| :--- | :--- |
| **[loki_overview.md](./loki_overview.md)** | Базовые концепции Loki, LogQL, архитектура |
| **[docker_compose_setup.md](./docker_compose_setup.md)** | Настройка Loki в Docker Compose |
| **[loki_stack_setup_guide.md](./loki_stack_setup_guide.md)** | Развертывание в Kubernetes с Helm |
| **[Grafana Alloy](../Grafana/grafana_alloy_overview.md)** | Рекомендуемый агент для новых развертываний |
| **[Fluent Bit Configuration](../Kubernetes/MonitoringLogging/EFK/fluentbit/fluentbit_configuration.md)** | Базовая конфигурация Fluent Bit |
| **[Fluent Bit Output: Loki](https://docs.fluentbit.io/manual/pipeline/outputs/loki)** | Официальная документация Fluent Bit |
