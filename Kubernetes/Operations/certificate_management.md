# Управление сертификатами Kubernetes через kubeadm

## Определения

**kubeadm** — утилита для управления жизненным циклом сертификатов Control Plane в кластерах, развёрнутых через `kubeadm init`.

**CA (Certificate Authority)** — корневой центр сертификации, подписывающий все сертификаты кластера. Подробнее: [PKI Overview](../../Security/Concepts/pki_overview.md).

**Leaf Certificates** — конечные (листовые) сертификаты компонентов (apiserver, kubelet), подписанные CA.

**Admin kubeconfig** — файл конфигурации (`admin.conf`), содержащий клиентский сертификат для административного доступа к кластеру.

### Ключевые сертификаты Control Plane

| Сертификат | Назначение | Подписан |
| :--- | :--- | :--- |
| **ca.crt** (Root CA) | Основной центр сертификации кластера | Self-signed |
| **etcd/ca.crt** | Центр сертификации для etcd | Self-signed |
| **front-proxy-ca.crt** | Для агрегации API | Self-signed |
| **apiserver.crt** | API Server (обслуживание клиентов) | ca |
| **apiserver-etcd-client.crt** | API Server → etcd | etcd-ca |
| **etcd/server.crt** | etcd Server | etcd-ca |

## Основные концепции

### Срок действия и автоматизация

| Тип сертификата | Срок действия | Управление через kubeadm |
| :--- | :--- | :--- |
| **Корневые CA** | 10 лет | ❌ Только ручная ротация |
| **Сертификаты компонентов** | 1 год | ✅ Автоматически или вручную |
| **Admin kubeconfig** | 1 год | ✅ Автоматически или вручную |

> **Важно:** Обновление версии Kubernetes через `kubeadm upgrade` автоматически продлевает все сертификаты, управляемые `kubeadm`.

### Требования к инфраструктуре

Для корректной работы `kubeadm certs`:
* Кластер должен быть инициализирован через `kubeadm`.
* Узел должен иметь доступ к файлам в `/etc/kubernetes/pki`.
* Внешние центры сертификации (External CA) не поддерживаются командами `renew`.

### Настройка сроков (kubeadm v1.31+)

Сроки действия можно переопределить в `ClusterConfiguration`:

```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
certificateValidityPeriod: 8760h      # Листовые сертификаты (1 год)
caCertificateValidityPeriod: 87600h   # CA сертификаты (10 лет)
```

## Практические сценарии

Все операции выполняются на узле Control Plane от имени суперпользователя.

### Проверка срока действия

```bash
sudo kubeadm certs check-expiration
```
**Результат:**
```text
CERTIFICATE                EXPIRES                  RESIDUAL TIME   CERTIFICATE AUTHORITY   EXTERNALLY MANAGED
admin.conf                 Feb 27, 2027 10:00 UTC   364d            -                       no
apiserver                  Feb 27, 2027 10:00 UTC   364d            ca                      no
apiserver-etcd-client      Feb 27, 2027 10:00 UTC   364d            etcd-ca                 no
...
```

### Ручное обновление сертификатов

**Продление всех сертификатов:**
```bash
sudo kubeadm certs renew all
# → [certs] Certificate for 'admin.conf' renewed
# → [certs] Certificate for 'apiserver' renewed
# ...
```

**Продление конкретного компонента:**
```bash
# Обновление сертификата API Server
sudo kubeadm certs renew apiserver
```

### Применение изменений

После обновления сертификатов необходимо перезапустить компоненты Control Plane, чтобы они начали использовать новые файлы.

**Способ 1: Перезапуск через Kubelet (для статических подов)**
```bash
sudo systemctl restart kubelet
# → Kubelet перезапустит поды API Server, Scheduler и Controller Manager
```

**Способ 2: Временное перемещение манифестов**
Если Kubelet не подхватил изменения:
```bash
sudo mv /etc/kubernetes/manifests/*.yaml /tmp/
sleep 20
sudo mv /tmp/*.yaml /etc/kubernetes/manifests/
# → Компоненты будут принудительно перезапущены
```

### Обновление Admin Kubeconfig

После выполнения `kubeadm certs renew all` сертификат в `/etc/kubernetes/admin.conf` обновляется. Его необходимо скопировать пользователю:
```bash
cp /etc/kubernetes/admin.conf $HOME/.kube/config
chown $(id -u):$(id -g) $HOME/.kube/config
```

## Диагностика и устранение проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Сертификаты истекли** | Пропущен срок обновления | `kubeadm certs renew all` + перезапуск компонентов |
| **x509: certificate expired** | Расхождение времени или истечение | Проверить `ntp`, выполнить `renew all` |
| **Unable to connect to API** | Истек `admin.conf` | Обновить сертификаты и скопировать новый `admin.conf` |
| **etcd connection refused** | Истек `apiserver-etcd-client` | Продлить сертификат etcd-client и перезапустить API Server |

## Дополнительная информация

### Лучшие практики

* **Резервное копирование:** Всегда делайте бэкап `/etc/kubernetes/pki` перед ротацией.
* **Мониторинг:** Настройте алерты за 30 дней до истечения (см. [Предотвращение истечения SSL](./ssl_expiration_prevention.md)).
* **Автоматизация:** Используйте `kubeadm upgrade` для регулярного обновления версий и сертификатов.
* **Kubelet Serving:** Включите `serverTLSBootstrap: true` в конфигурации Kubelet для автоматической подписи серверных сертификатов узлов.

### Ограничения

* `kubeadm` не обновляет сертификаты, если используется внешний CA (флаг `--external-ca`).
* Ротация корневого CA (`ca.crt`) — сложный ручной процесс, не поддерживаемый одной командой `kubeadm`.
* Изменение SAN (Subject Alternative Names) в сертификатах требует повторного выполнения `kubeadm init phase certs apiserver`.

### Связанные темы

* [Предотвращение истечения SSL](./ssl_expiration_prevention.md) — мониторинг и общая стратегия.
* [Обновление кластера](./upgrading_clusters.md) — плановое обновление версий.
* [PKI Overview](../../Security/Concepts/pki_overview.md) — теоретические основы инфраструктуры ключей.
* [Cert-manager Scenarios](../ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md) — управление сертификатами приложений.
