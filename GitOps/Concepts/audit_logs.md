# Ведение audit logs при GitOps-подходе

> Эта заметка фокусируется на специфике аудита в контексте GitOps. Общие принципы и требования к аудиторским логам описаны в документе **[Роль журналов в аудите и обеспечении соответствия требованиям](../../Security/audit_and_compliance_overview.md)**.

Audit logs в GitOps — это сквозная трассируемость изменений от коммита в репозитории до применённых объектов в кластере. Цель — установить, кто инициировал изменение, что именно изменилось, где это применилось, когда произошло, на какую ревизию кода ссылается событие и каков итог применения.

## Что фиксировать
*   Идентификатор ревизии: commit SHA или тег.
*   Инициатор: пользователь/бот, ключ, сервисный аккаунт.
*   Контекст: окружение, кластер, namespace, контроллер.
*   Объект и действие: ресурс Kubernetes, операция (create/update/patch/delete/apply).
*   Результат: успех/ошибка, дифф, причина отклонения (policy), корреляционный ID пайплайна.
*   Временные метки: поступление события, время применения в кластере.

## Источники аудита в GitOps
| Источник | Что фиксируется | Как интегрировать |
| --- | --- | --- |
| Git-история | Автор, ревизия, дифф | Обязательное подписывание коммитов и мерджей, защищённые ветки |
| K8s API Audit | Все вызовы к API | Политика аудита apiserver и отправка в централизованное хранилище |
| Контроллеры CD | События синхронизации, ревизии | Логи и Events ArgoCD/Flux, метки и аннотации на ресурсах |
| Admission/Policy | Нарушения правил | Логи OPA/Gatekeeper или Kyverno в режиме audit |
| Регистры образов | Источник артефакта | Привязка образов по digest, запрет плавающих тегов |

## Argo CD: точки аудита
Argo CD аннотирует и помечает управляемые ресурсы, что позволяет связать коммит и применённые объекты. Полезные маркеры:
*   label `argocd.argoproj.io/instance` для группировки ресурсов приложением
*   аннотации `sync-wave` и прочие для порядка и статуса

Извлечение событий по приложениям:
```bash
kubectl get events -n argocd --field-selector involvedObject.kind=Application -o wide
```
Соответствие ревизий и синхронизаций:
```bash
argocd app history my-app
kubectl -n argocd logs deploy/argocd-application-controller --since=1h
```
Практично собирать логи `argocd-application-controller` и `argocd-server` в централизованное хранилище с парсингом полей `revision`, `destNamespace`, `destServer` и `result`.

## Flux: точки аудита
Flux контроллеры (source-, kustomize-, helm-, notification-) публикуют события с ревизиями источников.
```bash
flux get kustomizations -A
flux logs --all-namespaces --since=1h
kubectl get events -A --field-selector involvedObject.kind=Kustomization
```
Flux проставляет метаданные:
*   `kustomize.toolkit.fluxcd.io/name` и `namespace` владельца
*   аннотации с `checksum` и ревизиями источников

`Notification Controller` может ретранслировать события на вебхуки SIEM/лог-систем.

## Kubernetes Audit Policy для GitOps-агентов
Точная фиксация вызовов от сервисных аккаунтов контроллеров обеспечивает воспроизводимость расследований. Политика аудита определяет, какие запросы и на каком уровне детализации логировать, чтобы уменьшить шум и обеспечить полноту для критичных операций.

Пример политики:
```yaml
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
# Логировать метаданные для всех критичных изменений ресурсов
- level: Metadata
  verbs: ["create","update","delete","patch","deletecollection"]
  resources:
  - group: "*"
    resources: ["deployments","secrets","configmaps","roles","rolebindings"]

# Для сервисного аккаунта деплоя логировать тело запроса и ответа
- level: RequestResponse
  users: ["system:serviceaccount:ci:deployer"]
  verbs: ["create","update"]

# Не логировать неинформативные события
- level: None
  resources:
  - group: ""
    resources: ["events"]
```

## Корреляция событий
*   Связывайте Git-коммит с применением: фиксируйте `revision` в логах контроллеров и в событиях K8s.
*   Используйте неизменяемые образы по `digest` и храните их mapping в артефакт-репозитории.
*   Централизуйте сбор: логи контроллеров, Kubernetes Audit, Events; нормализуйте поля (`cluster`, `env`, `app`, `revision`).
*   Обеспечьте неизменность логов и синхронизацию времени; включайте обязательное подписывание коммитов и мерджей.
