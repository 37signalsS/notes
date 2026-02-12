# Kube2iam и Kiam (Deprecated)

## Kube2iam (Deprecated)

```
Архитектура Kube2iam:

┌─────────────────────────────────────────────────────────────┐
│                    KUBERNETES NODE                          │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Pod A     │  │   Pod B     │  │   Pod C     │         │
│  │ (iam-role-a)│  │ (iam-role-b)│  │ (iam-role-c)│         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                │
│         │                │                │                │
│         └────────────────┼────────────────┘                │
│                          │ IPtables/NFTABLES               │
│                          │ (redirect 169.254.169.254)       │
│                          ▼                                │
│                   ┌──────────────┐                        │
│                   │  Kube2iam    │                        │
│                   │   Daemon     │                        │
│                   │ (hostNetwork)│                        │
│                   └──────┬───────┘                        │
│                          │                                │
└──────────────────────────┼────────────────────────────────┘
                           │ STS AssumeRole
                           ▼
                    ┌──────────────┐
                    │   AWS IAM    │
                    └──────────────┘
```

### Проблемы Kube2iam

1. **Security**: Pod может получить credentials другого Pod
2. **Reliability**: Kube2iam pod failure = нет доступа
3. **Complexity**: iptables rules, host networking
4. **Deprecated**: AWS не рекомендует использовать

## Kiam (Deprecated)

### Архитектура Kiam (Server-Agent)

```
┌─────────────────────────────────────────────────────────────┐
│                    KUBERNETES CLUSTER                       │
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   Pod A     │    │   Pod B     │    │   Pod C     │     │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘     │
│         │                  │                  │            │
│         │ gRPC             │ gRPC             │ gRPC       │
│         └──────────────────┼──────────────────┘            │
│                            │                              │
│                   ┌────────▼────────┐                     │
│                   │   Kiam Agent    │  (DaemonSet)        │
│                   │   (gRPC proxy)  │                     │
│                   └────────┬────────┘                     │
│                            │                              │
│         ┌──────────────────┼──────────────────┐           │
│         │                  │                  │           │
│  ┌──────▼──────┐    ┌──────▼──────┐    ┌──────▼──────┐    │
│  │Kiam Server 1│    │Kiam Server 2│    │Kiam Server 3│    │
│  │  (cache)    │    │  (cache)    │    │  (cache)    │    │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    │
│         │                  │                  │           │
└─────────┼──────────────────┼──────────────────┼───────────┘
          │                  │                  │
          └──────────────────┼──────────────────┘
                             │ STS AssumeRole
                             ▼
                      ┌──────────────┐
                      │   AWS IAM    │
                      └──────────────┘
```

### Преимущества Kiam над Kube2iam

- **Server-Agent архитектура**: Better reliability
- **Credential caching**: Reduced STS calls
- **Granular policies**: Server-side enforcement
- **Audit logging**: Centralized logging

**Но все равно deprecated в пользу IRSA**

## Сравнение решений

| Критерий | IRSA | Kube2iam | Kiam |
|----------|------|----------|------|
| **AWS Native** | ✅ Да | ❌ Нет | ❌ Нет |
| **Fine-grained** | ✅ Pod level | ✅ Pod level | ✅ Pod level |
| **Security** | ✅ OIDC-based | ⚠️ IP-based | ⚠️ gRPC proxy |
| **Reliability** | ✅ No single point | ❌ Daemon failure | ⚠️ Server failure |
| **Complexity** | ✅ Low | ⚠️ Medium | ⚠️ High |
| **Status** | ✅ Рекомендуется | ❌ Deprecated | ❌ Deprecated |
