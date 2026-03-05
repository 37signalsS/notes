# Node Unavailability: Проблемы с Kubelet

## 1. Kubelet остановлен или не отвечает

**Симптомы:**

- Статус узла: `NotReady` или `Unknown`
- `systemctl status kubelet` показывает `inactive` или `failed`

**Причины:**

- Сбой процесса kubelet
- Ошибка конфигурации
- Нехватка ресурсов

**Решение:**

```bash
# Перезапуск kubelet
sudo systemctl restart kubelet

# Проверка логов
journalctl -u kubelet -n 100 --no-pager

# Проверка конфигурации
cat /var/lib/kubelet/config.yaml
```

## 2. Проблемы с сертификатами kubelet

**Симптомы:**

- Kubelet не может подключиться к API server
- В логах: `x509: certificate has expired`

**Диагностика:**

```bash
# Проверка срока действия сертификата
openssl x509 -in /var/lib/kubelet/pki/kubelet.crt -text -noout | grep -A 2 "Validity"

# Проверка через kubeadm (если используется)
kubeadm certs check-expiration
```

**Решение:**

```bash
# Обновление сертификатов через kubeadm
sudo kubeadm certs renew all
sudo systemctl restart kubelet

# Или пересоздание сертификата kubelet
# См. [`../../../Operations/certificate_management.md`](../../../Operations/certificate_management.md)
```
