# Falco: Безопасность среды выполнения (Runtime Security)

## Определения

**Falco** ([falco.org](https://falco.org/)) — опенсорсный стандарт для обнаружения угроз в среде выполнения (Runtime Security) на хостах Linux, в контейнерах и кластерах Kubernetes. Инструмент анализирует поток системных вызовов (syscalls) на уровне ядра и сопоставляет их с библиотекой правил для выявления аномалий и подозрительной активности.

Проект является частью Cloud Native Computing Foundation (CNCF) на стадии Graduated и обеспечивает критический слой защиты «глубокой обороны» (Defense-in-Depth), обнаруживая угрозы, которые пропустили статические сканеры и политики Admission Control.

## Основные концепции

### Архитектура и механизм работы

Falco работает в пространстве пользователя (userspace), но получает данные непосредственно из ядра Linux через драйверы сбора событий:

1.  **Сбор событий (Drivers):** Перехват системных вызовов (open, exec, connect, etc.).
2.  **Движок правил (Engine):** Фильтрация и сопоставление событий с YAML-правилами.
3.  **Вывод (Outputs):** Отправка алертов в логи, stdout, gRPC или внешние системы через Falcosidekick.

### Типы драйверов инструментовки

В современных инфраструктурах (2025–2026) выбор драйвера критичен для стабильности нод:

| Драйвер | Метод | Особенности |
| :--- | :--- | :--- |
| **Modern eBPF** | eBPF (CO-RE) | Рекомендуемый стандарт. Не требует `kernel-devel`, минимальный оверхед, максимальная безопасность. |
| **eBPF Probe** | Классический eBPF | Для старых ядер (4.14+). Требует компиляции или загрузки прекомпилированных модулей. |
| **Kernel Module** | LKM | Устаревший метод. Требует сборки под конкретное ядро, потенциально может вызвать Kernel Panic. |

### Управление правилами через falcoctl

`falcoctl` — это CLI-инструмент для управления жизненным циклом Falco, включая установку драйверов и обновление наборов правил как OCI-артефактов:

```bash
# Проверка и обновление правил
falcoctl artifact follow falco-rules
```

## Установка и базовая настройка

В Kubernetes Falco развертывается как **DaemonSet** для покрытия всех узлов.

### Установка через Helm

```bash
helm repo add falcosecurity https://falcosecurity.github.io/falcosecurity
helm repo update

# Установка с использованием Modern eBPF и Sidekick
helm install falco falcosecurity/falco \
  --set driver.kind=modern-ebpf \
  --set falcosidekick.enabled=true
```

## Практические сценарии

### Синтаксис правил: Macros и Lists

Правила Falco строятся на переиспользуемых блоках:
-   **Lists:** Списки значений (порты, пути, имена процессов).
-   **Macros:** Логические условия (например, `is_container`).
-   **Rules:** Финальная логика алертинга.

Пример обнаружения записи в системные директории:

```yaml
- list: system_binary_dirs
  items: [/bin, /sbin, /usr/bin, /usr/sbin]

- macro: open_write_action
  condition: (evt.type = open or evt.type = openat) and fd.directory in (system_binary_dirs)

- rule: Write to System Binary Directory
  desc: Обнаружена попытка записи в системную директорию бинарных файлов.
  condition: open_write_action and not proc.name in (apt, yum, dnf, dpkg)
  output: >
    Критическое событие: Попытка записи в системную директорию 
    (user=%user.name command=%proc.cmdline file=%fd.name container=%container.id)
  priority: CRITICAL
```

### Мониторинг чувствительных файлов Kubernetes

Обнаружение доступа к токенам сервисных аккаунтов со стороны подозрительных процессов:

```yaml
- rule: Unauthorized access to K8s service account tokens
  desc: Detect access to service account tokens by non-authorized processes.
  condition: >
    fd.name startswith "/var/run/secrets/kubernetes.io/serviceaccount/"
    and not proc.name in (kube-proxy, node-exporter, calico-node)
  output: "Подозрительный доступ к K8s токену (user=%user.name proc=%proc.name file=%fd.name)"
  priority: WARNING
```

### Автоматизированное реагирование с Falcosidekick

Falcosidekick расширяет возможности Falco, позволяя реализовать **Active Response**:

1.  **Уведомления:** Отправка в Slack, Telegram, MS Teams.
2.  **Хранение:** Экспорт в Elasticsearch, Loki, InfluxDB.
3.  **Реагирование:** Вызов AWS Lambda или Google Cloud Functions для удаления скомпрометированного пода (Pod Isolation).
4.  **Визуализация:** Использование **Falcosidekick UI** для анализа трендов безопасности.

## Дополнительная информация

### Сравнение с другими инструментами

- **[Tetragon](../../Docker/Docker_security/runtime_monitoring.md):** Также использует eBPF, но фокусируется на **Enforcement** (блокировка вызовов внутри ядра), тогда как Falco сильнее в **Detection** (сложная логика и контекст событий).
- **[Kyverno](../../Kubernetes/Security/kyverno/policies/practical_scenarios.md):** Работает на этапе Admission Control (предотвращение создания плохих ресурсов). Falco дополняет его, отслеживая поведение уже запущенных ресурсов.
- **[kube-bench](../../Kubernetes/Security/kube-bench.md):** Проводит статический аудит конфигураций (CIS Benchmark), Falco обеспечивает динамический аудит событий.

### См. также
- [Мониторинг безопасности в Runtime](../../Docker/Docker_security/runtime_monitoring.md)
- [Безопасность eBPF в Kubernetes](../../Kubernetes/Networking/Network/CNI/ebpf.md)
- [Аудит событий в Kubernetes](../../Kubernetes/Security/audit.md)
