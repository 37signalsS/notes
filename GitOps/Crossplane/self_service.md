# Crossplane: Self-Service и Internal Developer Portal

## Определения

**Self-Service (самообслуживание)** — модель, где приложенческие команды заказывают инфраструктуру через простой, типизированный API (Claim), не касаясь провайдеров, креденшелов и композиций.

**Internal Developer Portal (IDP)** — внутренний каталог и точка входа для разработчиков (Backstage, Port). **Golden Path** — одобренный, поддерживаемый шаблон доставки (от Claim до продакшена).

**Разделение ответственности:** platform-инженеры пишут XRD + Composition + Functions и публикуют Claims как каталог; app-команды лишь заполняют параметры Claim.

## Базовые концепции

- Claim — это «заказ» высокоуровневого ресурса. Crossplane превращает его в десятки облачных/кубернетес-ресурсов незаметно для заказчика.
- IDP (Backstage) показывает доступные Claims, их статус (`Ready`/`Synced`) и зависимости; форма заполнения маппится в `spec.parameters` Claim.
- Платформенная команда контролирует допустимые значения через OpenAPI-схему XRD (`spec.versions[].schema`), политики (см. [Governance](./policy_governance.md)) и `EnvironmentConfig` (регион/аккаунт по умолчанию).
- App-командам **не дают** прямого доступа к `ProviderConfig`, MR и кредам — только к Claim в своём неймспейсе (см. [Мультитенантность](./multi_tenancy.md)).

## Практические сценарии

### 1. Claim как self-service API
```yaml
# App-команда подаёт только это — платформа делает остальное
apiVersion: platform.example.com/v1alpha1
kind: PostgreSQLInstance        # Claim (publishNames)
metadata:
  name: app-db
  namespace: team-a
spec:
  parameters:
    dbName: appdb
    size: medium
    environment: production
  compositionSelector:
    matchLabels:
      provider: yandex
  writeConnectionSecretToRef:
    name: app-db-connection
    namespace: team-a
```
Platform-инженеры заранее опубликовали XRD `XPostgreSQLInstance` с `claimNames: PostgreSQLInstance` и Composition, генерирующую БД + секреты подключения.

### 2. Связка с IDP (Backstage / Score)
- **Backstage:** Software Template создаёт Claim; Entity карточки отображают статус через Kubernetes-плагин. Каталог «Platform Capabilities» = список доступных XRD.
- **Score / Humanitec:** декларативное описание workload (`score.yaml`) рендерится платформой в Claim Crossplane (через платформенный оператор).
- Golden Path = репозиторий с XRD + Composition + политиками + примером Claim, доставляемый в кластер через GitOps (см. [GitOps Integration](./gitops_integration.md)).

### 3. Ограничения и риски
- Не давайте app-командам `cluster-admin` и доступ к `ProviderConfig`/секретам кредов.
- Фиксируйте допустимый набор значений в OpenAPI-схеме XRD, иначе Claim позволит заказать слишком большой/дорогой ресурс.
- Контролируйте стоимость и безопасность через политики (см. [Governance](./policy_governance.md)) и `Usage` (см. [защита зависимостей](./usage_protection.md)).

## Дополнительная информация

- [Backstage (Internal Developer Portal)](https://backstage.io/docs/)
- [Score (абстракция workload)](https://score.dev/)

Смежные темы:
- [Обзор Crossplane](./overview.md) — XRD/Composition/Claim на концептуальном уровне.
- [Мультитенантность и OOO](./multi_tenancy.md) — изоляция команд.
- [Политики и Governance](./policy_governance.md) — ограничение того, что можно заказать.
- [GitOps Integration](./gitops_integration.md) — доставка платформенных пакетов.
