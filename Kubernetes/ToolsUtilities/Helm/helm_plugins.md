# Плагины Helm

Расширение функциональности Helm CLI через сторонние скрипты, исполняемые файлы и модули WebAssembly (WASM). В Helm v4 (стандарт 2026 года) система плагинов обеспечивает изоляцию через WASM-песочницу и нативную поддержку OCI-реестров.

---

## Определения

| Термин | Описание |
|--------|----------|
| **Плагин (Plugin)** | Автономный инструмент, интегрируемый в `helm` CLI для расширения его возможностей. |
| **WASM-плагин** | (Helm v4+) Плагин, скомпилированный в WebAssembly, работающий в изолированной среде (Extism runtime). |
| **Метаданные (`plugin.yaml`)** | Файл манифеста плагина, определяющий его имя, версию, тип и конфигурацию среды выполнения. |
| **Тип плагина (Plugin Type)** | (v4) Обязательная типизация: `cli/v1` (команды), `getter/v1` (протоколы), `postrenderer/v1` (модификация манифестов). |
| **WASM-песочница (Sandbox)** | Изолированная среда выполнения с ограниченным доступом к сети, ФС и переменным окружения. |

---

## Базовые концепции

### Управление плагинами

Плагины устанавливаются в директорию `$HELM_PLUGINS` (по умолчанию `~/.local/share/helm/plugins`). В версии v4 основным методом дистрибуции стал OCI (Open Container Initiative).

| Команда | Описание |
|---------|----------|
| `helm plugin install <url\|path>` | Установка плагина (GitHub, локальная папка или OCI-артефакт). |
| `helm plugin list` | Вывод списка всех установленных плагинов и их версий. |
| `helm plugin update <name>` | Обновление плагина до последней доступной версии. |
| `helm plugin uninstall <name>` | Удаление плагина из системы. |
| `helm plugin package <dir>` | (v4) Упаковка плагина в OCI-совместимый артефакт `.tgz`. |

### Архитектура и среда выполнения

1.  **Классические плагины (Subprocess):** Запускаются как дочерние процессы (Binary/Bash). Наследуют переменные окружения и имеют полный доступ к ФС пользователя. В v4 считаются "легаси" из-за отсутствия изоляции.
2.  **WASM-плагины (Extism runtime):** Современный стандарт. Модуль `.wasm` исполняется в песочнице. Все разрешения (сеть, переменные, пути ФС) должны быть декларативно описаны в `plugin.yaml`.

**Стандартные переменные окружения (доступны всем типам плагинов):**
*   `HELM_BIN` — путь к исполняемому файлу `helm`.
*   `HELM_PLUGIN_DIR` — путь к директории с файлами самого плагина.
*   `HELM_NAMESPACE` — текущий неймспейс из контекста Kubernetes.
*   `HELM_KUBECONTEXT` — имя текущего контекста кластера.

---

## Разработка плагина

### Структура манифеста `plugin.yaml`

Файл `plugin.yaml` является входной точкой и определяет поведение плагина в системе.

```yaml
apiVersion: v1
name: "my-advanced-plugin"
version: "1.2.0"
type: "cli/v1"
runtime: "extism/v1"  # Указывается для WASM-плагинов

# Инструкции для CLI
config:
  usage: "my-advanced-plugin [args]"
  shortHelp: "Краткое описание для helm help"

# Настройки безопасности и изоляции (только для WASM)
runtimeConfig:
  module: "plugin.wasm"
  allowedHosts:
    - "api.github.com"  # Белый список доменов для сетевых вызовов
  allowedEnv:
    - "KUBECONFIG"      # Доступ к конкретным переменным окружения
  timeout: 30000        # Ограничение времени выполнения в миллисекундах
```

### Публикация в OCI-реестры

Helm v4 позволяет хранить плагины в тех же реестрах, что и чарты (Harbor, ECR, GHCR).

```bash
# 1. Упаковка
helm plugin package ./my-plugin

# 2. Авторизация и пуш
helm registry login registry.example.com
helm push my-advanced-plugin-1.2.0.tgz oci://registry.example.com/plugins

# 3. Установка конечным пользователем
helm plugin install oci://registry.example.com/plugins/my-advanced-plugin --version 1.2.0
```

### Отладка WASM-плагинов

Поскольку WASM-плагины работают в изоляции, их отладка требует использования логов среды выполнения:

1.  **Уровень логирования:** Используйте флаг `--debug` при запуске команд Helm для вывода системных сообщений WASM-хоста.
2.  **Stdout/Stderr:** Весь вывод плагина в стандартные потоки пробрасывается в консоль пользователя.
3.  **WASM-инспекция:** Используйте инструменты типа `wasm-objdump` или `wasm-interp` для проверки структуры модуля перед упаковкой.

---

## Практические сценарии

### helm-diff: Визуализация изменений

Самый востребованный плагин для GitOps. Показывает разницу между текущим состоянием ресурсов в кластере и тем, что определено в чарте. В v4 плотно интегрирован с **Server-Side Apply**.

```bash
# Просмотр изменений перед апгрейдом
helm diff upgrade my-app ./charts/my-app --values values.yaml
# → Output: показывает diff между текущим SSA-состоянием и новым чартом

# Сравнение двух ревизий релиза
helm diff revision my-app 10 11
```

### helm-secrets: Управление секретами

Интеграция с **Mozilla SOPS** для шифрования данных. Позволяет использовать зашифрованные файлы значений напрямую в командах Helm.

```bash
# Установка плагина
helm plugin install https://github.com/jkroepke/helm-secrets

# Деплой с расшифровкой на лету
helm secrets upgrade --install my-app ./chart -f values.yaml -f secrets.yaml
```

### helm-unittest: Юнит-тестирование чартов

Позволяет писать BDD-тесты на YAML для проверки корректности рендеринга шаблонов без Kubernetes.

```bash
# Запуск тестов
helm unittest ./my-chart
# → Output: PASSED: 15, FAILED: 0
```

### helm-mapkubeapis: Исправление устаревших API

Помогает при миграции между версиями Kubernetes, обновляя аннотации ресурсов в метаданных релиза, чтобы они соответствовали новым версиям API.

```bash
# Обновление метаданных релиза
helm mapkubeapis my-release
```

---

## Дополнительная информация

### Post-rendering и плагины

В Helm v4 механизм `--post-renderer` требует, чтобы исполнитель был зарегистрированным плагином с типом `postrenderer/v1`. Это повышает безопасность, предотвращая выполнение произвольных скриптов.

```bash
# Использование плагина-пострендерера (например, для kustomize)
helm upgrade --install my-app ./chart --post-renderer kustomize-plugin
```

### Полезные ссылки

*   [Artifact Hub (поиск плагинов)](https://artifacthub.io/)
*   [HIP-0026: Helm v4 Plugin System](https://github.com/helm/community/blob/main/hips/hip-0026.md)
*   [Официальная документация по WASM SDK](https://helm.sh/docs/wasm-sdk/)

См. также:
*   [Обзор Helm](./helm_overview.md) — архитектура v4 и SSA
*   [Безопасность Helm](./Advanced/security_best_practices.md) — лучшие практики
*   [Helmfile](./helmfile_overview.md) — декларативное управление
*   [Argo CD: Custom Tooling](../../../GitOps/ArgoCD/argocd_custom_tooling.md) — интеграция плагинов в GitOps-пайплайны
