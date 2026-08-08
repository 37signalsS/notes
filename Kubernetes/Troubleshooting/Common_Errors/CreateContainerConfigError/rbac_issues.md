# CreateContainerConfigError: Проблемы с RBAC и ServiceAccount

## Определения

**RBAC-related CreateContainerConfigError** — критическое состояние пода, возникающее на этапе подготовки конфигурации, когда `kubelet` не может получить доступ к необходимым ресурсам (Secret, ConfigMap) или подготовить токены аутентификации из-за ограничений безопасности или ошибок конфигурации прав доступа.

Хотя `kubelet` обладает собственной системной идентичностью, современные механизмы безопасности (NodeRestriction, Bound Service Account Tokens) делают процесс разрешения зависимостей пода чувствительным к настройкам **RBAC (Role-Based Access Control)** и **ServiceAccount**.

Подробные определения ошибки: [definitions.md](./definitions.md).

## Основные концепции

### Механизмы ограничения доступа

1.  **Admission-контроллер NodeRestriction:**
    Ограничивает возможности `kubelet` по получению объектов `Secret` и `ConfigMap`. `kubelet` может прочитать только те ресурсы, которые используются подами, **запланированными на данный конкретный узел**. Если планировщик или API-сервер имеют несогласованность, `kubelet` получит отказ в доступе (403 Forbidden), что приведет к `CreateContainerConfigError`.
2.  **Проекция токенов (ServiceAccountToken Projection):**
    Начиная с K8s 1.22+, токены ServiceAccount не хранятся в вечных секретах, а генерируются динамически через проецируемые тома. Ошибки в настройках API-сервера (`--service-account-issuer`) или отсутствие прав на создание `tokenreviews` могут заблокировать формирование конфигурации контейнера.
3.  **Изоляция через Namespace:**
    Ресурсы (Secret, ConfigMap, PVC) и ServiceAccount **всегда** должны находиться в одном и том же Namespace. RBAC-роли (`Role`) также ограничиваются пространством имен, если не используются `ClusterRole`.

### Типичные причины возникновения ошибки

| Причина | Механизм | Результат |
| :--- | :--- | :--- |
| **Отсутствие SA** | Под ссылается на `serviceAccountName`, которого нет в API | Ошибка генерации токена в `projected volume` |
| **NodeRestriction** | Попытка прочитать Secret, не «привязанный» к узлу | Ошибка 403 от API-сервера для `kubelet` |
| **CSI RBAC** | Нехватка прав у SA пода для работы с CSI-драйвером | Сбой монтирования внешнего секрета (Vault/AWS) |
| **Automount disabled** | `automountServiceAccountToken: false` при необходимости доступа к API | Ошибка приложения (но не `CreateContainerConfigError`) |

## Практические сценарии

### Сценарий 1: ServiceAccount не найден или удален

Часто возникает при использовании Helm-чартов, где создание SA отключено, но имя указано вручную.

**Диагностика:**
```bash
# Проверка имени SA в поде
kubectl get pod <pod-name> -o jsonpath='{.spec.serviceAccountName}'
# Проверка существования объекта
kubectl get sa <sa-name>
# → Error from server (NotFound): serviceaccounts "<sa-name>" not found
```

### Сценарий 2: Ошибки прав в CSI Secret Store

При интеграции с внешними хранилищами (HashiCorp Vault, Azure Key Vault) через CSI-драйвер, права ServiceAccount критичны для этапа монтирования.

**Диагностика через impersonation (имитация прав):**
```bash
# Может ли SA "читать" секреты в своем пространстве имен?
kubectl auth can-i get secrets --as=system:serviceaccount:<namespace>:<sa-name>
# → no  <-- Если ответ 'no', монтирование тома через CSI может не сработать.
```

### Сценарий 3: Проблемы с ServiceAccountToken в защищенных кластерах

В кластерах с жестким аудитом (например, GKE Autopilot или ванильный K8s с PSP/Admission Policies) создание токенов может быть ограничено.

**Симптом в событиях:**
```text
Events:
  Warning  FailedMount  ...  MountVolume.SetUp failed for volume "kube-api-access-xxxx" : failed to generate token: secrets "default-token-xxxx" not found
```
**Примечание:** В версиях 1.24+ ищите ошибки, связанные с `TokenRequest` API, а не с объектами `Secret`.

### Сценарий 4: Ограничения NodeRestriction (Для администраторов)

Если под застрял в `CreateContainerConfigError` с ошибкой `Forbidden` для `kubelet`, проверьте, что под действительно назначен на этот узел.

```bash
# Проверка соответствия узла
kubectl get pod <pod-name> -o wide
# Если узел верный, но ошибка сохраняется — проверьте логи kube-apiserver на предмет блокировок NodeRestriction.
```

## Список проверок (Checklist)

1.  **Существование:** ServiceAccount существует в том же Namespace, что и Pod.
2.  **Имена:** Нет опечаток в поле `serviceAccountName` в PodSpec.
3.  **Namespace:** Все ресурсы (Secrets, CM) находятся в одном Namespace с Подом.
4.  **RBAC Bindings:** Для приложений, использующих CSI Secret Store, созданы `RoleBinding` к соответствующему ServiceAccount.
5.  **Token Automount:** Если приложению нужен токен доступа (например, для работы с Vault), убедитесь, что `automountServiceAccountToken` не установлен в `false`.

## Дополнительная информация

### Связанные ресурсы

- [Общая диагностика CreateContainerConfigError](./diagnostics.md)
- [Проблемы с Secret](./secret_issues.md)
- [Безопасность ServiceAccount и токенов](../../../Base/secrets/security.md)
- [Концепции RBAC: Роли и привязки](../../../Security/rbac/rbac_overview.md)
- [Обзор CSI Driver](../../../Storage/CSI/csi_overview.md)
