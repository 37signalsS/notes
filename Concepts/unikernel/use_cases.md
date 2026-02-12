# Сценарии использования Unikernels

## 1. Edge Computing

```
┌─────────────────────────────────────────────────────────────┐
│                    EDGE LOCATION                            │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │  DNS Cache  │  │  SSL Term.  │  │  Firewall   │         │
│  │  (MirageOS) │  │ (IncludeOS) │  │ (Rumprun)   │         │
│  │  ~2MB       │  │  ~5MB       │  │  ~3MB       │         │
│  │  10ms boot  │  │  15ms boot  │  │  12ms boot  │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│                                                             │
│  Преимущества:                                              │
│  - Мгновенный старт на edge-устройствах                     │
│  - Минимальное использование ресурсов                       │
│  - Высокая плотность размещения                             │
└─────────────────────────────────────────────────────────────┘
```

## 2. Serverless / Function-as-a-Service

```yaml
# AWS Firecracker + MicroVMs (unikernel-подобный подход)
# Запуск функций за миллисекунды

apiVersion: v1
kind: Pod
metadata:
  name: firecracker-microvm
spec:
  runtimeClassName: firecracker
  containers:
  - name: function
    image: my-unikernel-function:latest
    resources:
      limits:
        memory: "32Mi"
        cpu: "100m"
```

## 3. High-Performance Applications

- **High-frequency trading**: Минимальная latency
- **CDN edge nodes**: Быстрый старт, высокая плотность
- **IoT gateways**: Малый footprint, безопасность

## 4. Security Appliances

- **VPN concentrators**
- **Firewall appliances**
- **IDS/IPS sensors**
