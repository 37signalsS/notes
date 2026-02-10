# Ведение audit logs при GitOps-подходе

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
*   label argocd.argoproj.io/instance для группировки ресурсов приложением
*   аннотации sync-wave и прочие для порядка и статуса

Извлечение событий по приложениям:
```sql
kubectl get events -n argocd --field-selector involvedObject.kind=Application -o wide
```
Соответствие ревизий и синхронизаций:
```applescript
argocd app history my-app
kubectl -n argocd logs deploy/argocd-application-controller --since=1h
```
Практично собирать логи argocd-application-controller и argocd-server в централизованное хранилище с парсингом полей revision, destNamespace, destServer и result.

## Flux: точки аудита
Flux контроллеры (source-, kustomize-, helm-, notification-) публикуют события с ревизиями источников.
```sql
flux get kustomizations -A
flux logs --all-namespaces --since=1h
kubectl get events -A --field-selector involvedObject.kind=Kustomization
```
Flux проставляет метаданные:
*   kustomize.toolkit.fluxcd.io/name и namespace владельца
*   аннотации с checksum и ревизиями источников

Notification Controller может ретранслировать события на вебхуки SIEM/лог-систем.

## Kubernetes Audit Policy для GitOps-агентов
Точная фиксация вызовов от сервисных аккаунтов контроллеров обеспечивает воспроизводимость расследований. Пример минимальной политики аудита:
```vbnet
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
  - level: Metadata
    users: ["system:serviceaccount:argocd:argocd-application-controller"]
  - level: Metadata
    users:
      - "system:serviceaccount:flux-system:kustomize-controller"
      - "system:serviceaccount:flux-system:helm-controller"
  - level: RequestResponse
    verbs: ["update","patch","create","delete","deletecollection"]
    resources:
      - group: "*"
        resources: ["*"]
```
## Корреляция событий
*   Связывайте Git-коммит с применением: фиксируйте revision в логах контроллеров и в событиях K8s.
*   Используйте неизменяемые образы по digest и храните их mapping в артефакт-репозитории.
*   Централизуйте сбор: логи контроллеров, Kubernetes Audit, Events; нормализуйте поля (cluster, env, app, revision).
*   Обеспечьте неизменность логов и синхронизацию времени; включайте обязательное подписывание коммитов и мерджей.
