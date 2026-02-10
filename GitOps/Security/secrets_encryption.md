# Безопасность и шифрование секретов в GitOps

GitOps подразумевает хранение декларативных манифестов в Git, но обычный Kubernetes Secret — это лишь base64-кодирование, а не защита. Главная задача — перенести источник истины для конфигурации в Git, при этом исключив утечку чувствительных данных, обеспечить контроль ключей шифрования и воспроизводимость расшифровки в кластере.

## Подходы к управлению секретами
| Подход | Что лежит в Git | Где происходит расшифровка | Ключи и права | Плюсы | Ограничения |
| --- | --- | --- | --- | --- | --- |
| Sealed Secrets (Bitnami) | SealedSecret (зашифрованные поля) | В кластере, контроллером | Ключ хранится у контроллера, ротация по процедуре | Простота для ArgoCD/Flux, не нужны внешние KMS | Привязка к кластеру/ключу, миграции требуют ре-шифрование |
| SOPS (Age/GPG/KMS) | Обычные манифесты с зашифрованными полями и секцией sops | До применения (Flux умеет нативно), либо плагином в Argo CD | Управление ключами в KMS/age/GPG, гранулярный доступ | Универсальность, аудит доступа в KMS | Нужна настройка плагинов/секретов с ключами |
| External Secrets Operator | В Git лежит ссылка (ExternalSecret), а не сам секрет | Контроллер читает из Vault/SM/KMS | Политики в менеджере секретов | Нет секретов в Git, удобная ротация | Зависимость от внешнего хранилища и его доступности |

## Пример: Flux + SOPS (age)
Шифруется только чувствительная часть, остальная структура прозрачна для ревью и диффов.

Пример зашифрованного секрета (файл secret.enc.yaml):
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: app
type: Opaque
data:
  DATABASE_URL: ENC[AES256_GCM,data:...,iv:...,tag:...,type:str]
sops:
  encrypted_regex: '^(data|stringData)$'
  mac: ENC[AES256_GCM,...]
  age:
    - recipient: age1qxyz...
  version: '3.7.3'
```
Flux расшифрует манифесты при применении:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: sops-age
  namespace: flux-system
type: Opaque
data:
  age.agekey: BASE64_СОДЕРЖИМОЕ_ФАЙЛА_key.txt
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: app
  namespace: flux-system
spec:
  interval: 1m
  path: ./manifests
  sourceRef:
    kind: GitRepository
    name: app-repo
  decryption:
    provider: sops
    secretRef:
      name: sops-age
```
Ключ age хранится в Secret только в кластере. Доступ к нему ограничивается RBAC и NetworkPolicies.

## Пример: Sealed Secrets для Argo CD и Flux
Оба инструмента применяют CRD, а расшифровка выполняется контроллером в кластере:
```yaml
apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata:
  name: app
spec:
  encryptedData:
    PASSWORD: AgB3...
  template:
    metadata:
      name: app
    type: Opaque
```
Контроллер создаст обычный Secret на основе зашифрованного содержимого. При смене ключа Sealed Secrets требуется пере-зашифровать объекты.

## Ключи, права и ротация
*   Минимизируйте blast radius: ключи на уровень среды (dev/stage/prod), отдельные роли KMS для групп команд.
*   Ротация: SOPS — пересоздание зашифрованных файлов командой ротации; Sealed Secrets — выпуск нового ключа контроллера и ре-шифрование.
*   Зафиксируйте процедуры восстановления: где хранится корневой ключ, кто может инициировать Key Rotation, как валидировать результат в кластере.

## Политики и операционные практики
*   Запрет на прямые Secret из Git: политика Admission (Kyverno/Gatekeeper) блокирует создание Secret пользователями; исключения — сервис-аккаунты контроллеров Sealed Secrets/External Secrets.
*   Разделяйте репозитории и права: секреты и инфраструктуру держите в отдельных репо/директориях с отдельными ACL и обязательным code review.
*   Исключайте утечки: секреты в .gitignore, сканирование коммитов на утечки, запрет логирования манифестов с расшифрованными данными, включение редактирования секретов в UI Argo CD с маскировкой.
*   Контроль диффов: используйте опции скрытия diff чувствительных ключей, чтобы они не попадали в артефакты проверок и уведомления.
