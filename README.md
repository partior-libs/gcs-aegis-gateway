# GCS Aegis Gateway

A highly secure, high-performance, and centralized secret fetching gateway for GitHub Actions. 

**Aegis Gateway** currently fetches secrets dynamically from secrets managers such as **GCP Secret Manager**, **AWS Secrets Manager**, and native GitHub Secrets/Variables directly into your GitHub Actions runner. 

By utilizing Just-In-Time (JIT) access and OIDC (OpenID Connect) Workload Identity Federation, Aegis Gateway eliminates the need to persistently mount entire secret vaults into ephemeral runners (such as via External Secrets Operator), significantly reducing the blast radius in the event of a compromised runner.

---

## 🚀 Key Features

*   **Platform Support**: Native integrations for GCP Secret Manager, AWS Secrets Manager, and GitHub Secrets/Vars.
*   **High Performance**: Uses thread-safe concurrent API fetching to grab hundreds of secrets in seconds.
*   **Separation of Concerns**: Platform engineers define *where* secrets live and *how* to authenticate (`central_configs`). Application developers simply define *which* secrets they need (`aegis-link` repo configs).
*   **Secure Outputs**: Automatically masks all fetched secrets in GitHub logs. Injects secrets securely into environment variables (`$GITHUB_ENV`) or directly into temporary files with strict **0600 permissions** (ideal for certificates).
*   **Version Pinning**: Supports specific secret versions and labels (AWS `VersionStage`).

---

## 📖 How It Works

The gateway operates on a two-tier configuration model:

1.  **Central Configuration (`central_configs/*.yaml`)**: Managed by the Platform/Security team. It acts as a directory mapping a logical secret name (e.g., `psql-dapps-client-cert`) to its physical cloud location (e.g., `projects/123/secrets/...`) and authentication profile.
2.  **Application Configuration (`config/<org>/<repo>.yaml`)**: Managed by Developers. It lists the logical secrets the specific repository requires for its CI/CD pipeline and where to place them (env var or file).

When the Action runs, it cross-references the App Config with the Central Config, authenticates using OIDC, fetches the payloads concurrently, and provisions them to the runner.

---

## ⚙️ Inputs

| Input | Description | Required | Default |
| :--- | :--- | :---: | :--- |
| `org` | GitHub organisation name | No | Extracted from `github.repository` |
| `repo` | GitHub repository name | No | Extracted from `github.repository` |
| `config-file` | Path to the repo YAML config file | No | `config/<org>/<repo>.yaml` |
| `central-config-file` | Path to central config. Defaults to `<env>.yaml` or loads ALL `*.yaml`. | No | `config/central_configs/*.yaml` |
| `auth-profiles-file` | Path to the auth profiles YAML file | No | `config/auth_profiles.yaml` |
| `provider` | Filter to fetch only a specific provider (e.g., `gcp`, `aws`, `gh-secret`) | No | `all` |
| `env` | Target environment to filter secrets for (e.g., `devnet02`) | No | `None` |
| `secrets-json` | JSON string of GitHub secrets (`${{ toJson(secrets) }}`) | **Yes** | |
| `vars-json` | JSON string of GitHub variables (`${{ toJson(vars) }}`) | **Yes** | |
| `gcp-workload-identity-provider` | GCP WIF Provider for OIDC authentication | No | *(Preconfigured default)* |
| `gcp-service-account` | GCP Service Account to impersonate | No | *(Preconfigured default)* |
| `aws-region` | AWS Region | No | `ap-southeast-1` |
| `aws-role-to-assume` | AWS IAM Role ARN to assume via OIDC | No | *(Preconfigured default)* |
| `aws-role-session-name` | Session name for AWS STS assume role | No | `gh-actions-session` |

---

## 🏗️ Configuration Guide

### 1. Central Configuration (Platform Team)

Central configurations tell the gateway *how* to find a secret in the cloud. These files live in `config/central_configs/`.

**Best Practice:** Segregate your configs by environment (e.g., `devnet02.yaml`, `sitnet01.yaml`). If the GitHub Action receives `env: devnet02`, it will automatically load `config/central_configs/devnet02.yaml`. If no `env` is provided, it will load and aggregate **all** `.yaml` files in the folder.

**Example: `config/central_configs/devnet02.yaml`**
```yaml
---
aegis-gateway:
  # GCP Secret Manager Example
  - name: psql-dapps-ptr1ga-client-cert
    env: devnet02
    type: gcp-secret-manager
    config:
      source: projects/732439461432/secrets/psql-dapps-ptr1ga-client-cert
      project: prj-dev-devnet02
      auth-profile: gcp-devnet02-target
      # version: "1"  # (Optional) Defaults to 'latest'.
      # json-key: "password" # (Optional) Extracts specific key from JSON secret.

  # AWS Secrets Manager Example
  - name: aws-test-secret-2
    env: devnet02
    type: aws-secret-manager
    config:
      source: psql-dapps-ptr4ae-user-username
      region: eu-west-1
      auth-profile: aws-eu-deploy-target
      # version: AWSPREVIOUS # (Optional) AWS VersionStage or Label.
```

### 2. JSON Key Extraction (`json-key`)

If a secret is stored as a JSON object (e.g., `{"username": "admin", "password": "secure123"}`), you can use the `json-key` parameter to extract a specific value.

*   **Behavior**: When `json-key` is provided, the gateway parses the secret payload as JSON and retrieves only the specified key.
*   **Flexibility**: You can define `json-key` in the **Central Config** (if a secret is globally always a JSON object) or in the **Application Config** (if you want to pull different keys from the same JSON secret into different variables/files).
*   **Safety**: If the secret is not valid JSON or the key is missing, the Action will fail securely.

### 3. Auth Profiles Configuration

Defines cross-account or cross-project impersonation details.

**Example: `config/auth_profiles.yaml`**
```yaml
gcp-devnet02-target:
  type: gcp-impersonate
  service-account: target-sa@prj-dev-devnet02.iam.gserviceaccount.com

aws-eu-deploy-target:
  type: aws-assume-role
  role-arn: arn:aws:iam::081403079551:role/target-deploy-role
  region: eu-west-1
```

### 3. Application / Repository Configuration (Dev Team)

Application configs tell the gateway *which* secrets to fetch for a specific repo, and *where* to put them. These files live in `config/<org>/<repo>.yaml`.

**Example: `config/partior-gh-ops/gh-runner-refresher.yaml`**
```yaml
---
aegis-link:
  # Fetching a database certificate and writing it securely to a file
  - name: psql-dapps-ptr1ga-client-cert
    type: gcp-secret-manager
    env: devnet02
    outputs:
      - type: file
        destination: ./tmp/secrets/psql-dapps-ptr1ga-client-cert.pem

  # Fetching an AWS secret and injecting it into an Environment Variable
  - name: aws-test-secret-2
    env: devnet02
    type: aws-secret-manager
    outputs:
      - type: value
        destination: AWS_SECRET_DEV
      - type: file
        destination: ./tmp/secrets/aws_secret_1.txt
```

---

## 💻 Usage in GitHub Actions

To invoke the gateway, add the following step to your `.github/workflows/*.yaml` file. 

*Note: Ensure your job has `permissions: { id-token: 'write', contents: 'read' }` enabled for cloud OIDC to function properly.*

```yaml
jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: 'read'
      id-token: 'write'    # CRITICAL for GCP WIF / AWS OIDC
    env:
      environment: devnet02
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Fetch Required Secrets via Aegis Gateway
        uses: partior-libs/gcs-aegis-gateway@main
        with:
          secrets-json: ${{ toJson(secrets) }}
          vars-json: ${{ toJson(vars) }}
          env: ${{ env.environment }}
          # (Optional) Override auth endpoints
          # gcp-workload-identity-provider: 'projects/123/locations/global/workloadIdentityPools/...'
          # gcp-service-account: 'sa-gh-actions@...'
          # aws-region: 'eu-west-1'
          # aws-role-to-assume: 'arn:aws:iam::123:role/...'

      - name: Verify Secrets
        run: |
          echo "Verifying secrets were provisioned securely..."
          
          # 1. Use the Env Var securely (it is auto-masked by the gateway)
          if [ -z "${{ env.AWS_SECRET_DEV }}" ]; then
            echo "::error::AWS_SECRET_DEV env var is empty!"
            exit 1
          fi
          
          # 2. Use the File securely
          if [ ! -s "./tmp/secrets/psql-dapps-ptr1ga-client-cert.pem" ]; then
            echo "::error::Cert file is missing!"
            exit 1
          fi
          echo "Secrets are ready for deployment!"

---

## 🧪 Development and Testing

### Running Unit Tests
Aegis Gateway includes a comprehensive test suite using `pytest`. 

To run tests locally:
1.  **Set up a Virtual Environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
2.  **Install Dependencies**:
    ```bash
    pip install pytest pytest-cov pyyaml google-auth google-cloud-secret-manager boto3 yamllint
    ```
3.  **Run Tests**:
    ```bash
    export PYTHONPATH=scripts
    pytest tests/ -v
    ```

### CI/CD Pipeline
Unit tests are automatically executed on every Push or Pull Request to the `main` branch via the [Unit Tests](.github/workflows/unit-tests.yaml) GitHub Workflow.
```
