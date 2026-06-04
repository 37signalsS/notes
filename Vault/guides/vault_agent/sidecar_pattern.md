# Vault Agent Sidecar — динамическое обновление конфигурации

## Определения

**Vault Agent Sidecar** — паттерн использования `vault-agent` в качестве постоянно работающего sidecar-контейнера в Kubernetes-поде. Агент отслеживает изменения секретов в Vault, обновляет конфигурационные файлы и отправляет сигнал `SIGHUP` основному процессу приложения для перечитывания конфигурации без перезапуска пода.

Этот подход решает проблему статических конфигураций: стандартные механизмы Kubernetes не реагируют на изменения данных, доставляемых напрямую из Vault, так как сами ресурсы Kubernetes (Secret/ConfigMap) при этом не меняются.

## Основные концепции

### Архитектура пода

Для реализации паттерна под обычно включает три компонента:

1. **Init-контейнер Vault Agent:** выполняет первичную аутентификацию и генерирует начальную версию конфигурации, после чего завершается.
2. **Основной контейнер приложения:** использует сгенерированные файлы конфигурации.
3. **Sidecar-контейнер Vault Agent:** работает постоянно, отслеживает изменения секретов и уведомляет приложение об обновлениях.

### Межконтейнерное взаимодействие и безопасность

Для отправки сигналов (например, `SIGHUP`) между контейнерами требуется ослабить стандартную изоляцию Kubernetes.

**1. Использование `shareProcessNamespace: true`**
Объединяет PID-пространство всех контейнеров в поде. Это позволяет процессам в разных контейнерах видеть друг друга и отправлять сигналы.

* **Риски:** процессы одного контейнера могут видеть переменные окружения и файловые системы других контейнеров через `/proc`.

**2. Добавление Capability `SYS_PTRACE`**
Разрешает процессу отправлять сигналы процессам, которые ему не принадлежат.

```yaml
# Фрагмент спецификации пода
spec:
  shareProcessNamespace: true
  containers:
  - name: app
    # ...
  - name: vault-agent-sidecar
    securityContext:
      capabilities:
        add: ["SYS_PTRACE"]
```

**3. Единый идентификатор пользователя (UID)**
Для отправки сигналов без прав root все контейнеры должны работать под одним UID (параметр `runAsUser`).

## Практические сценарии

### Настройка Vault Agent для Sidecar

В конфигурации агента блок `template` должен содержать параметр `command` для отправки сигнала.

```hcl
# agent-config.hcl

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

template {
  source      = "/vault/configs/app.ctmpl"
  destination = "/etc/app/config.json"
  
  # Отправка сигнала SIGHUP процессу nginx
  command = "pkill -HUP nginx"
}
```

### Пример манифеста Deployment

Пример пода с Nginx, который перечитывает конфигурацию при обновлении секретов в Vault.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-vault-sidecar
spec:
  replicas: 1
  template:
    spec:
      shareProcessNamespace: true
      serviceAccountName: vault-auth
      volumes:
      - name: config-shared
        emptyDir: { medium: Memory }
      containers:
      - name: nginx
        image: nginx:alpine
        volumeMounts:
        - name: config-shared
          mountPath: /etc/nginx/conf.d
      - name: vault-agent-sidecar
        image: hashicorp/vault:1.16
        runAsUser: 101 # UID пользователя nginx
        securityContext:
          capabilities:
            add: ["SYS_PTRACE"]
        volumeMounts:
        - name: config-shared
          mountPath: /vault/configs
        env:
        - name: VAULT_ADDR
          value: "http://vault.vault.svc:8200"
        args: ["agent", "-config=/etc/vault/agent-config.hcl"]
```

## Дополнительная информация

### Сравнение методов доставки секретов

| Критерий | Vault Sidecar | Vault Injector | Secrets Store CSI |
| :--- | :--- | :--- | :--- |
| **Сложность** | Высокая (ручной YAML) | Низкая (аннотации) | Средняя (CRD) |
| **Гибкость** | Максимальная | Ограничена аннотациями | Стандартная для K8s |
| **Динамическая ротация** | Да (SIGHUP) | Да (SIGHUP) | Да (CSI Sync) |
| **Изоляция** | Ослаблена | Сохранена | Сохранена |

### Когда использовать ручной Sidecar

* **Сложная логика шаблонов:** когда требуются вложенные шаблоны или специфические команды обработки.
* **Тонкая настройка ресурсов:** контроль лимитов и прав `securityContext` для контейнера агента.
* **Отсутствие Injector:** если установка дополнительных компонентов в кластер запрещена.

### Связанные документы

* [Vault Agent: основы](./basics.md) — базовые концепции и синтаксис шаблонов.
* [Vault Injector](./injector.md) — автоматизация внедрения sidecar через аннотации.
* [Интеграция Vault с Kubernetes](../vault_kubernetes_integration.md) — общий обзор стратегий.
