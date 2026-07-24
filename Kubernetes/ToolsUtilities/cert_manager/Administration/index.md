# Администрирование cert-manager

## Определения

**Администрирование cert-manager** — управление жизненным циклом сертификатов, автоматизация очистки ресурсов, ротация ключей и обеспечение безопасности контроллера.

## Основные концепции

### Управление жизненным циклом ресурсов

#### Сборка мусора (Garbage Collection) и Secret

По умолчанию cert-manager **не удаляет** Kubernetes `Secret` при удалении ресурса `Certificate`. Это защитный механизм: случайное удаление CRD не должно приводить к потере рабочего TLS-сертификата.

**Проблема:** При использовании GitOps (ArgoCD/Flux) или частом пересоздании сертификатов в кластере накапливаются "осиротевшие" секреты.

**Решение:** Включение флага `--enable-certificate-owner-ref=true` добавляет `ownerReference` к Secret. Это связывает время жизни Secret с ресурсом Certificate.

#### Очистка CertificateRequest

В версиях до v1.18 ресурсы `CertificateRequest` (история запросов на выпуск) могли накапливаться тысячами, создавая нагрузку на etcd.

**Изменение в v1.18+:** Параметр `revisionHistoryLimit` теперь по умолчанию равен **1**. Это означает, что cert-manager автоматически удаляет старые запросы, оставляя только последний успешный. В старых версиях рекомендуется устанавливать этот параметр вручную в объекте `Certificate`.

### Безопасность и ротация ключей

#### Ротация приватных ключей (rotationPolicy)

Параметр `rotationPolicy` определяет, будет ли генерироваться новый приватный ключ при каждом продлении сертификата.

- `Never` (по умолчанию в старых версиях): Ключ не меняется. Снижает риск простоя, если приложение плохо обрабатывает смену ключа, но снижает безопасность.
- `Always` (рекомендуется для v1.18+): Новый ключ генерируется при каждом обновлении. Соответствует современным стандартам безопасности.

#### Распространение CA через trust-manager

Копирование Secret с CA-сертификатом между всеми namespace вручную — антипаттерн. Для этого используется аддон **trust-manager**, который позволяет создать ресурс `Bundle` и автоматически доставлять CA-сертификат во все ConfigMap кластера.

## Практические сценарии

### Сценарий: Настройка автоматической очистки и ротации (v1.18+)

Для обеспечения чистоты кластера и безопасности настройте `Certificate` следующим образом:

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: example-com
  namespace: default
spec:
  secretName: example-com-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  commonName: example.com
  # Оставляем только 1 CertificateRequest в истории (v1.18+ default)
  revisionHistoryLimit: 1
  # Принудительная ротация ключа при каждом обновлении
  rotationPolicy: Always
  dnsNames:
  - example.com
```

### Сценарий: Глобальное включение Garbage Collection через Helm

Если вы используете GitOps, рекомендуется включить автоматическое удаление Secret на уровне контроллера:

```bash
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --set installCRDs=true \
  --set "extraArgs={--enable-certificate-owner-ref=true}"
```

**Проверка работы:**
1. Создайте Certificate.
2. Убедитесь, что Secret имеет `ownerReferences`:
   ```bash
   kubectl get secret example-com-tls -o jsonpath='{.metadata.ownerReferences}'
   ```
3. Удалите Certificate и проверьте, что Secret исчез.

### Сценарий: Ограничение сетевого доступа (v1.20+)

Начиная с версии v1.20, Helm-чарт поддерживает создание нативных `NetworkPolicy`. Это позволяет ограничить трафик только необходимыми направлениями (K8s API и ACME-серверы).

```bash
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --set global.networkPolicy.enabled=true
```

### Сценарий: Диагностика "зависших" ресурсов

Если Certificate застрял в `Pending`, проверьте связанные ресурсы по цепочке:

1. **CertificateRequest:**
   ```bash
   kubectl describe certificaterequest <name>
   ```
2. **Order (для ACME):**
   ```bash
   kubectl describe order <name>
   ```
3. **Challenge:**
   ```bash
   kubectl describe challenge <name>
   ```

Подробные шаги см. в [руководстве по troubleshooting](./troubleshooting.md).

## Дополнительная информация

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| Garbage collection | **10** | Официальная документация cert-manager.io |
| revisionHistoryLimit | **10** | Изменение поведения по умолчанию в v1.18 |
| rotationPolicy | **10** | Введено в v1.10, рекомендуется в v1.18+ |
| trust-manager | **9** | Официальный суб-проект cert-manager |
| NetworkPolicy | **10** | Добавлено в Helm-чарт v1.20 |

### Смотрите также

- **[Cert-manager: Операции](./operations.md)** — мониторинг, backup и обновление
- **[Cert-manager: Troubleshooting](./troubleshooting.md)** — глубокая диагностика проблем
- **[Cert-manager: Установка](../installation.md)** — параметры Helm и CRD
