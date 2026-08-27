# Crossplane: Безопасность цепочки поставок пакетов

## Определения

**Supply chain security (безопасность цепочки поставок)** для Crossplane — защита OCI-пакетов (Providers, Configurations, Functions), которые Crossplane тянет из реестра. Поскольку пакет = OCI-образ, к нему применимы те же риски, что к обычным образам: подмена тега, компрометация реестра/пайплайна, внедрение вредоносного провайдера.

**Подписание (cosign)** — криптографическая подпись образа пакета по digest; проверка — по публичному ключу (`--validation-pem`) или keyless (Fulcio/Rekor).

**packagePullSecrets** — Kubernetes-секрет (`dockerconfigjson`), по которому Crossplane авторизуется в приватном реестре при скачивании пакета.

## Базовые концепции

- Тег mutable: `:v0.14.1` может указывать на разные байты в разное время. **Подписывайте и пинируйте по digest** (`@sha256:...`), а не по тегу.
- Crossplane умеет проверять подписи пакетов **до установки** через cosign (альфа-фича `EnableAlphaSignatureVerification`; публичный ключ передаётся через `--validation-pem`). Без флага пакеты ставятся без проверки.
- Доверие: либо фиксированный публичный ключ (key-based), либо keyless (OIDC-идентичность пайплайна + Rekor-лог). Keyless сильнее: доказывает, *кто* подписал.
- Приватные реестры: креды передаются через `packagePullSecrets` у `Provider`/`Configuration` (либо `Configuration`/`Provider` наследуют из неймспейса).

> **Важно (адвайзори 2026):** CVE/адвайзори GHSA-wfqx-gjrf-g28r (июнь 2026) описывает TOCTOU в проверке подписей пакетов Crossplane — при установке по тегу реестр может отдать подписанный образ для проверки, а затем другой при установке. Всегда **пинируйте по digest** и при необходимости дублируйте проверку вне Crossplane (см. ниже).

## Практические сценарии

### 1. Подписание пакета (в CI)
```bash
# генерация пары ключей (или keyless через OIDC в пайплайне)
cosign generate-key-pair

# ВСЕГДА подписывайте по digest, а не по тегу
cosign sign --key cosign.key \
  xpkg.upbound.io/yandexcloud/crossplane-provider-yc@sha256:<DIGEST>

# keyless (современный дефолт): COSIGN_EXPERIMENTAL=1 cosign sign <pkg>@<digest>
```

### 2. Включение проверки подписей в Crossplane
```bash
# в аргументах Deployment crossplane (через Helm values / флаги)
crossplane core start \
  --enable-signature-verification \     # альфа-фича EnableAlphaSignatureVerification
  --validation-pem="$(cat cosign.pub)"
```
При включении неподписанный (или подписанный чужим ключом) пакет не установится — в `ProviderRevision` появится условие ошибки верификации.

### 3. Приватный реестр через packagePullSecrets
```yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-yandex-cloud
spec:
  package: xpkg.upbound.io/yandexcloud/crossplane-provider-yc:v0.14.1
  packagePullSecrets:
    - name: registry-pull-secret
```
```bash
kubectl -n crossplane-system create secret docker-registry registry-pull-secret \
  --docker-server=registry.example.com \
  --docker-username=<user> --docker-password=<pass>
```

### 4. Независимая проверка ( defence-in-depth)
Не полагайтесь только на alpha-проверку Crossplane. Проверяйте образ в CI и/или на входе в кластер:
```bash
# проверка подписи перед применением пакета
cosign verify --key cosign.pub \
  xpkg.upbound.io/yandexcloud/crossplane-provider-yc@sha256:<DIGEST>

# либо admission-контроль на уровне кластера (connaisseur, Kyverno image verification,
# cosign-gatekeeper-provider) — блокирует любой неподписанный образ, включая xpkg
```

### 5. Минимальный чек-лист для продакшена
- Пакеты только из доверенного реестра, **зафиксированы по digest**.
- Подписаны cosign; Crossplane включает проверку (`--enable-signature-verification` + `--validation-pem`).
- Приватные реестры — через `packagePullSecrets`, креды не в Git (ESO/SOPS, см. [GitOps Integration](./gitops_integration.md)).
- Версии пакетов проверяются на свежесть (см. [Обновление и миграция](./upgrade_migration.md)).

## Дополнительная информация

- [Providers (установка, packagePullSecrets, верификация)](https://docs.crossplane.io/latest/packages/providers/)
- [Signature Verification (Crossplane, DeepWiki)](https://deepwiki.com/crossplane/crossplane/4.5-signature-verification)
- [Verifying Signatures (Sigstore/cosign)](https://docs.sigstore.dev/cosign/verifying/verify)
- [Адвайзори TOCTOU при верификации подписей (2026)](https://github.com/crossplane/crossplane/security/advisories/GHSA-wfqx-gjrf-g28r)

Смежные темы:
- [GitOps Integration](./gitops_integration.md) — доставка пакетов через GitOps, секреты (ESO/SOPS).
- [Политики и Governance (Kyverno/OPA)](./policy_governance.md) — проверка образов на входе в кластер.
- [Обновление и миграция](./upgrade_migration.md) — ревизии и свежесть пакетов.
- [Обзор Crossplane](./overview.md).
