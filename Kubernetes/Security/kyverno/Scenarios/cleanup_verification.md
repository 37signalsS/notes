# Очистка ресурсов и верификация образов в Kyverno

## Определения

**Автоматическая очистка (Cleanup)** — процесс удаления устаревших, завершенных или временных объектов Kubernetes по расписанию или достижению срока жизни (TTL). Реализуется через специализированные контроллеры Kyverno для поддержания гигиены кластера и разгрузки `etcd`.

**Верификация образов (Image Verification)** — комплекс мер по проверке подлинности, целостности и происхождения контейнерных образов. Включает проверку цифровых подписей (Sigstore/Cosign), аттестаций (результаты сканирования, SBOM) и мутацию тегов в неизменяемые дайджесты (Digest).

---

## Основные концепции

### Механизмы контроля жизненного цикла

В версиях 1.12+ Kyverno разделяет задачи очистки и верификации на специализированные API:

| Механизм | Ресурс / Поле | Назначение | Технология |
| :--- | :--- | :--- | :--- |
| **Cleanup Policy** | `ClusterCleanupPolicy` | Массовое удаление по расписанию. | `kyverno.io/v2` |
| **Resource TTL** | `cleanup.kyverno.io/ttl` | Индивидуальное удаление по метке. | TTL Controller |
| **Image Validation** | `ImageValidatingPolicy` | Проверка подписей и аттестаций. | CEL / Sigstore |

### Защита цепочки поставок (Supply Chain)

Современный подход Kyverno (2025) базируется на проверке не только факта подписи, но и метаданных артефакта:
1.  **Keyless Signing**: Использование OIDC-идентификаторов (GitHub, Google) вместо статических ключей.
2.  **Attestations**: Проверка наличия SBOM (Software Bill of Materials) и отчетов о сканировании уязвимостей.
3.  **Digest Enforcement**: Принудительная замена тегов (например, `:latest`) на SHA-хеши для защиты от атак подмены.

---

## Практические сценарии

### 1. Автоматическая очистка по TTL (Метки)

Самый быстрый способ управления жизненным циклом временных ресурсов в Dev/Stage средах.

```yaml
# Пример добавления TTL к временному пространству имен
apiVersion: v1
kind: Namespace
metadata:
  name: temp-feature-branch
  labels:
    # Ресурс будет удален через 4 часа после создания
    cleanup.kyverno.io/ttl: "4h"
```

### 2. Массовая очистка завершенных заданий (CleanupPolicy)

**Проблема**: Большое количество завершенных `Jobs` и их подов создают нагрузку на API-сервер.

**Решение**: Политика для удаления всех завершенных заданий старше 24 часов.

```yaml
apiVersion: kyverno.io/v2
kind: ClusterCleanupPolicy
metadata:
  name: cleanup-finished-jobs
spec:
  schedule: "0 1 * * *" # Запуск в 01:00 каждую ночь
  match:
    any:
      - resources:
          kinds:
            - batch/v1/Job
  conditions:
    all:
      - key: "{{ target.status.completionTime }}"
        operator: GreaterThan
        value: "24h"
```

### 3. Верификация подписей и SBOM (CEL-based)

**Проблема**: Необходимость гарантировать, что образ подписан в CI/CD и содержит актуальный SBOM.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ImageValidatingPolicy
metadata:
  name: verify-trusted-images
spec:
  matchImageReferences:
    - "ghcr.io/my-org/*"
  attestors:
    - entries:
        - keyless:
            issuer: "https://token.actions.githubusercontent.com"
            subject: "https://github.com/my-org/app-repo/.github/workflows/release.yaml@refs/heads/main"
  attestations:
    - name: check-sbom
      type: "https://cyclonedx.org/schema" # Проверка наличия аттестации SBOM
```

---

## Дополнительная информация

### Рекомендации по эксплуатации

1.  **Кэширование верификации**: Включайте кэширование результатов верификации в `image-verify-cache`, чтобы избежать избыточных запросов к реестру и повысить производительность запуска подов.
2.  **Deletion Propagation**: При настройке очистки используйте `Foreground` удаление, чтобы гарантировать корректное завершение зависимых ресурсов.
3.  **Исключения (PolicyException)**: Используйте стандартный механизм исключений для временного разрешения образов без подписи (например, при отладке в Sandbox).
4.  **Audit First**: Новые политики верификации образов внедряйте в режиме `Audit`, чтобы не заблокировать работу кластера из-за ошибок в CI/CD пайплайнах.

### См. также

- **[Агрегированные роли](../additional.md)** — настройка прав для контроллера очистки.
- **[Отчеты Kyverno](../reports.md)** — анализ результатов верификации.
- **[Типы правил](../rules.md)** — синтаксис `verifyImages` и `mutate`.
- **[Официальная документация по Cleanup](https://kyverno.io/docs/cleanup-resources/)**
