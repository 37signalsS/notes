# Vault Agent Sidecar: Динамическое Обновление Конфигурации

## Definitions

**Vault Agent Sidecar** — паттерн использования `vault-agent` в качестве постоянно работающего sidecar-контейнера в Kubernetes-поде. Агент отслеживает изменения секретов в Vault, перерендеривает конфигурационные файлы и отправляет сигнал `SIGHUP` основному процессу приложения для перечитывания конфигурации без перезапуска пода.

**Проблема:** стандартные Kubernetes-механизмы (`Reloader`, `ConfigMap`/`Secret` watches) не реагируют на изменения секретов, доставляемых напрямую из Vault (например, через CSI-драйвер или ручной sidecar), так как Kubernetes-ресурсы не меняются.

**Решение:** sidecar-контейнер `vault-agent` с блоком `command` в шаблоне, выполняющий `pkill -HUP <process>` при каждом обновлении файла.

## Basic Concepts

### Архитектура пода

Под состоит из трёх контейнеров:

1. **`initContainer` (`vault-agent`)** — однократно генерирует первоначальную версию конфигурационного файла из шаблона и секретов, завершает работу.
2. **Основной контейнер приложения** (например, `nginx`) — использует сгенерированный файл конфигурации.
3. **`sidecar`-контейнер (`vault-agent`)** — работает постоянно, периодически проверяет изменения секретов, перерендеривает файл и отправляет `SIGHUP` процессу в основном контейнере.

### Ослабление изоляции контейнеров

Для отправки сигналов между контейнерами требуется компромисс в безопасности:

```yaml
# Фрагмент Deployment.yaml
spec:
  template:
    spec:
      shareProcessNamespace: true
      containers:
        - name: application
          image: nginx:latest
        - name: vault-agent-sidecar
          image: vault:latest
          securityContext:
            capabilities:
              add: ["SYS_PTRACE"]
```

#### `shareProcessNamespace: true`

Объединяет PID-namespace для всех контейнеров в поде.

**Последствия для безопасности:**

- **Нет PID 1** — основной процесс в контейнере не имеет PID 1, что может нарушить работу приложений, ожидающих роль `init`-процесса.
- **Видимость процессов** — процессы из одного контейнера видны другим (через `ps` или `/proc`).
- **Доступ к файловой системе** — через `/proc/{pid}/root` один контейнер может получить доступ к файловой системе другого.

#### `capabilities.add: ["SYS_PTRACE"]`

Linux capability, разрешающая процессу отправлять сигналы процессам, которые ему не принадлежат.

#### Единый пользователь (`runAsUser`)

Для отправки сигналов без `root` все контейнеры должны работать под одним UID. Если приложение работает от `nginx` (UID 101), `vault-agent` должен использовать `runAsUser: 101`.

## Practical Scenarios

### Конфигурация Vault Agent для Sidecar

```hcl
# vault-agent-sidecar-config.hcl

vault {
  address = "http://vault.vault.svc:8200"
}

auto_auth {
  method "kubernetes" {
    mount_path = "auth/kubernetes"
    config = {
      role = "my-app-role"
    }
  }
}

# exit_after_auth = false (по умолчанию) — агент продолжает работать

template {
  source      = "/vault/configs/nginx.ctmpl"
  destination = "/usr/share/nginx/html/index.html"

  # Команда для поиска PID nginx и отправки SIGHUP
  command = "pkill -HUP nginx"
}
```

**Ключевые параметры:**

- **`exit_after_auth: false`** — агент не завершает работу, продолжает отслеживать секреты.
- **`command = "pkill -HUP nginx"`** — после каждого обновления файла `vault-agent` находит все процессы с именем `nginx` в общем PID-namespace и отправляет `SIGHUP` для перечитывания конфигурации.

### Полный пример манифеста

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-with-vault-sidecar
spec:
  replicas: 1
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      shareProcessNamespace: true
      serviceAccountName: vault-auth
      volumes:
        - name: config-volume
          emptyDir:
            medium: Memory
      initContainers:
        - name: vault-agent-init
          image: vault:latest
          volumeMounts:
            - name: config-volume
              mountPath: /vault/configs
          env:
            - name: VAULT_ADDR
              value: "http://vault.vault.svc:8200"
      containers:
        - name: nginx
          image: nginx:latest
          volumeMounts:
            - name: config-volume
              mountPath: /usr/share/nginx/html
        - name: vault-agent-sidecar
          image: vault:latest
          runAsUser: 101
          securityContext:
            capabilities:
              add: ["SYS_PTRACE"]
          volumeMounts:
            - name: config-volume
              mountPath: /vault/configs
          env:
            - name: VAULT_ADDR
              value: "http://vault.vault.svc:8200"
```

## Additional Information

### Сравнение подходов доставки секретов

| Критерий | Ручной Sidecar | Vault Injector | Secrets Store CSI |
| :--- | :--- | :--- | :--- |
| Гибкость | Полный контроль | Ограничено аннотациями | Стандартный CSI |
| Динамическая ротация | Да (`command` + `SIGHUP`) | Да (через аннотации) | Да (`rotation: true`) |
| Модификация манифестов | Ручная | Автоматическая | Ручная |
| Ослабление изоляции | Требуется | Не требуется | Не требуется |
| Сложность | Высокая | Низкая | Средняя |

### Когда использовать ручной Sidecar

- **Сложная логика:** кастомные шаблоны, несколько источников секретов.
- **Тонкая настройка:** контроль `securityContext`, `resources`, `command`.
- **Air-gapped среды:** установка дополнительных компонентов нежелательна.
- **Приложения с горячей перезагрузкой:** поддержка `SIGHUP` (Nginx, HAProxy, Prometheus).

### Безопасность

Паттерн требует тщательной оценки рисков из-за ослабления изоляции контейнеров. Альтернативы без ослабления изоляции:

- **[Vault Injector](./injector.md)** — автоинъекция через Mutating Admission Webhook.
- **[Secrets Store CSI Driver](../vault_kubernetes_integration.md)** — монтирование секретов как томов.

### Связанные документы

- Основы Vault Agent: [Vault Agent: основы](./basics.md)
- Автоматическая инъекция: [Vault Injector](./injector.md)
- Обзор интеграции с Kubernetes: [Интеграция Vault с Kubernetes](../vault_kubernetes_integration.md)
