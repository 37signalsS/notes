#### 3. Развертывание вспомогательных компонентов

##### 3.1. Cert-Manager

Для управления TLS-сертификатами в кластере используется **[cert-manager](../../ToolsUtilities/cert_manager.md)**. Этот компонент необходим для автоматического выпуска сертификатов для Ingress-ресурсов (Grafana, Loki и т.д.).

В данном руководстве мы будем использовать самоподписанные сертификаты.

1. **Установите cert-manager**, следуя официальной инструкции, или воспользуйтесь нашей заметкой: **[Установка cert-manager](../ToolsUtilities/cert_manager.md#Установка)**.

2. **Создайте ClusterIssuer** для выпуска самоподписанных сертификатов. Это позволит обеспечить безопасное взаимодействие с веб-интерфейсами внутри кластера.

    ```bash
    # Создание корневого CA
    kubectl apply -f - <<EOF
    apiVersion: cert-manager.io/v1
    kind: ClusterIssuer
    metadata:
      name: minikube-ca
    spec:
      ca:
        secretName: minikube-ca-secret
    EOF

    kubectl apply -f - <<EOF
    apiVersion: cert-manager.io/v1
    kind: Certificate
    metadata:
      name: minikube-ca-secret
      namespace: cert-manager
    spec:
      isCA: true
      duration: 8760h # 1y
      secretName: minikube-ca-secret
      privateKey:
        algorithm: RSA
        size: 2048
      commonName: "minikube-ca"
      issuerRef:
        name: minikube-ca
        kind: ClusterIssuer
        group: cert-manager.io
    EOF
    ```

##### 3.2. Локальный Docker Registry

Разверните локальный Docker Registry, доступный внутри кластера.

```bash
# Установка Docker Registry
helm upgrade --install docker-registry twuni/docker-registry 
  --namespace docker-registry 
  --create-namespace 
  --set service.type=NodePort 
  --set service.nodePort=30000 
  --set ingress.enabled=true 
  --set ingress.host=registry.test 
  --set ingress.tls.enabled=true 
  --set ingress.tls.secretName=registry-tls 
  --set ingress.tls.issuerName=minikube-ca 
  --set ingress.tls.issuerKind=ClusterIssuer

# Добавление записи в /etc/hosts
echo "$(minikube ip) registry.test" | sudo tee -a /etc/hosts

# Настройка Docker Daemon для работы с insecure registry
minikube ssh "sudo tee /etc/docker/daemon.json <<< '{"insecure-registries": ["registry.test:30000"]}'"
minikube ssh "sudo systemctl restart docker"
minikube stop && minikube start

# Создание секрета для доступа к registry
kubectl create secret docker-registry regcred 
  --docker-server=registry.test:30000 
  --docker-username=admin 
  --docker-password=admin 
  --namespace default

kubectl patch serviceaccount default -p '{"imagePullSecrets": [{"name": "regcred"}]}'
```
