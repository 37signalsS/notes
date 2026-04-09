# Falco: Runtime Security Monitoring

## Definitions

**Falco** ([falco.org](https://falco.org/)) — open-source решение для мониторинга безопасности во время выполнения (runtime) на хостах, в контейнерах, Kubernetes и облачных средах. Falco отслеживает поведение процессов на уровне ядра Linux, выявляя подозрительную активность в реальном времени.

Проект поддерживается Cloud Native Computing Foundation (CNCF) и является де-факто стандартом для обнаружения угроз безопасности в runtime.

## Basic Concepts

Falco перехватывает системные вызовы ядра Linux через eBPF или модуль ядра и сравнивает их с правилами для выявления аномалий.

### Архитектура

- **Перехват событий:** eBPF или kernel module для мониторинга системных вызовов в реальном времени
- **Система правил:** YAML-правила описывают подозрительное поведение (запуск shell в контейнере, модификация критических файлов, аномальный сетевой доступ)

### Возможности

- Мониторинг системных вызовов через eBPF или kernel module
- Обнаружение: shell в контейнерах, изменение прав доступа, доступ к критическим файлам, аномальные сетевые запросы
- YAML-правила: встроенные (CIS-совместимые) или кастомные
- Интеграции: Kubernetes (kube-apiserver), AWS CloudTrail, GitHub для обогащения контекста
- Отправка событий через [Falcosidekick](https://github.com/falcosecurity/falcosidekick): Slack, Prometheus, Grafana, SIEM-системы

### Преимущества

Runtime-мониторинг Falco дополняет статический анализ и аудит конфигураций, обеспечивая критически важный слой защиты для облачных и контейнерных сред.

## Practical Scenarios

### Обнаружение shell в контейнере

Правило срабатывает при запуске интерактивной оболочки внутри контейнера — типичный первый шаг злоумышленника:

```yaml
- rule: Terminal shell in container
  desc: A shell was spawned in a container with an attached terminal.
  condition: >
    spawned_process and container and shell_procs and proc.tty != 0
  output: >
    Terminal shell in container (user=%user.name user_loginuid=%user.loginuid container_id=%container.id container_name=%container.name image=%container.image.repository:%container.image.tag)
  priority: NOTICE
```

### Модификация бинарных директорий

Обнаружение записи в `/bin`, `/sbin`, `/usr/bin`, `/usr/sbin` — возможная установка руткита:

```yaml
- rule: Write below binary dir
  desc: an attempt to write to any file below a set of binary directories
  condition: >
    (open_write) and
    (fd.directory in (/bin, /sbin, /usr/bin, /usr/sbin)) and
    (not package_mgmt_procs)
  output: >
    File created/modified in binary directory (user=%user.name command=%proc.cmdline file=%fd.name)
  priority: ERROR
```

### Чтение Kubernetes Secrets

Обнаружение попыток чтения Secrets в Kubernetes:

```yaml
- rule: Read K8s Secret
  desc: Detect any attempt to read a K8s secret.
  condition: >
    k8s_secret_read and not trusted_containers
  output: >
    K8s secret read (user=%user.name command=%proc.cmdline secret=%k8s.secret.name)
  priority: WARNING
```

### Интеграция с Falcosidekick

[Falcosidekick](https://github.com/falcosecurity/falcosidekick) маршрутизирует события Falco:

- Мессенджеры: Slack, Telegram
- SIEM: Elasticsearch, Splunk
- Алертинг: Prometheus Alertmanager
- Serverless: AWS Lambda, Google Cloud Functions (для автоматического реагирования — изоляция пода)

## Additional Information

### Сравнение с инструментами безопасности

- **[Kubesec](../../Kubernetes/Security/kubesec.md) / [Kyverno](../../Kubernetes/Security/kyverno/policies/practical_scenarios.md):** Проверка манифестов и политики до/во время деплоя (Admission Control). Falco работает после деплоя — runtime-мониторинг.
- **[kube-bench](../../Kubernetes/Security/kube-bench.md):** Аудит статической конфигурации на CIS Benchmark. Falco обнаруживает динамические угрозы в работающем кластере.
- **[Sigstore](./sigstore.md):** Безопасность supply chain (подпись/верификация артефактов). Falco обеспечивает безопасность артефактов во время выполнения.
