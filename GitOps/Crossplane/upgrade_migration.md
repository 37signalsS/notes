# Crossplane: Обновление, миграция и откат

## Определения

**Package Revision** — версия установленного пакета (Provider/Configuration/Function). При смене `spec.package` создаётся новая ревизия (`ProviderRevision`/`ConfigurationRevision`); активная определяется политикой.

**CompositionRevision** — версия Composition; контролируется `compositionRevisionHistoryLimit` и `defaultCompositionRevisionPolicy` (см. XRD).

**Rollback (откат)** — возврат к предыдущему желаемому состоянию. В GitOps-модели это revert коммита в Git; состояние облака Crossplane приводит к желаемому сам.

## Базовые концепции

### Как Crossplane обновляет пакеты
- Смена `spec.package` у `Provider`/`Configuration` → Crossplane тянет новый OCI-образ, создаёт ревизию, по политике делает её `Active`.
- При даунгрейде возможна несовместимость CRD (новые поля пропадают) → «осиротевшие» MR. Используйте `packageRevisionHistoryLimit`, чтобы держать N предыдущих.
- Провайдер нездоров (`HEALTHY=False`) при неудовлетворённых зависимостях — см. `kubectl describe providerrevisions`.

### Crossplane v2: ключевые ломающие изменения (миграция с v1)
- **Удалены встроенные connection-секреты из XR** (`spec.writeConnectionSecretToRef` у XR больше нет) — детали соединения пробрасываются иначе (через Composition/функции).
- **Удалён External Secret Store (ESS)** у provider-kubernetes и др. — только `Secret`.
- **Provider Families** — монолитные провайдеры заменяются семействами (ставьте только нужные сервисы).
- Перед миграцией используйте `v2 upgrade check` (`crossplane alpha ...`), сканирующий использование ESS и connection-секретов.

### Семантика отката
- **Git revert** возвращает манифесты в репо → ArgoCD/Flux синхронизирует → Crossplane приводит облако к новому(старому) желаемому состоянию. Это не «мгновенный откат облака», а реконсиляция.
- **Откат Composition** — переключение активной `CompositionRevision` (новая композиция генерирует другой набор ресурсов; Crossplane удалит/создаст diff).
- **Облачные ресурсы не откатываются автоматически** до предыдущего состояния — Crossplane лишь стремится к желаемому. Если старая версия удалила ресурс, он пересоздаётся.
- `deletionPolicy: Orphan` + `Usage` (см. [защита зависимостей](./usage_protection.md)) предотвращают нежелательное удаление при откате.

## Практические сценарии

### 1. Обновление провайдера
```bash
# вариант A: через CLI
crossplane xpkg update provider provider-yandex-cloud v0.14.1
# вариант B: просто обновите spec.package в Provider-манифесте и примените через GitOps
```
```bash
kubectl get providerrevisions
kubectl describe providerrevisions   # причина HEALTHY=False
```

### 2. История ревизий Composition
```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: CompositeResourceDefinition
metadata:
  name: xbuckets.platform.example.com
spec:
  # ...
  defaultCompositionRevisionPolicy: Ordered   # или Active, Automatic, Manual
  compositionRevisionHistoryLimit: 5          # хранить 5 прошлых ревизий
```

### 3. Откат через Git (типичный паттерн)
```bash
git revert <commit-с-плохой-composition>
git push   # ArgoCD подхватит, Crossplane приведёт облако к предыдущему состоянию
```
При удалении Claim используйте `defaultCompositeDeletePolicy: Foreground` (см. [защита зависимостей](./usage_protection.md)), чтобы дождаться чистого удаления дочерних ресурсов.

### 4. Диагностика при обновлении
| Симптом | Причина | Решение |
| --- | --- | --- |
| `HEALTHY=False` у Provider | несовместимость/нет сети/нет кредов | `kubectl describe providerrevisions`, логи провайдера |
| Осиротевшие MR после даунгрейда | CRD потеряла поля | поднять совместимую версию пакета |
| Лишние ресурсы после смены Composition | старая ревизия ещё Active | переключить активную `CompositionRevision` |
| `Synced=False` после migrate | ESS/connection-secret удалён в v2 | перенести логику в Composition/Secret |

## Дополнительная информация

- [Providers (обновление/удаление/верификация)](https://docs.crossplane.io/latest/packages/providers/)
- [Установка и обновление Crossplane](https://docs.crossplane.io/latest/get-started/install/)
- [Миграция конфигураций на v2 (Upbound)](https://docs.upbound.io/manuals/uxp/howtos/migrate-configurations-v2)

Смежные темы:
- [Защита зависимостей (Usage)](./usage_protection.md) — безопасное удаление/откат.
- [Тестирование платформы](./testing_crossplane.md) — проверка композиции до деплоя.
- [GitOps Integration](./gitops_integration.md) — bootstrap и синхронизация пакетов.
- [Обзор Crossplane](./overview.md).
