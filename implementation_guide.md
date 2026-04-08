# Security Chaos Engineering Framework - Implementation Guide

## Table of Contents
1. [Quick Start](#quick-start)
2. [Architecture Details](#architecture-details)
3. [Setting Up the Vulnerable Test System](#setting-up-test-system)
4. [Building Core Components](#building-core-components)
5. [Running Your First Test](#running-your-first-test)
6. [Expected Results](#expected-results)

---

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.10+
- Git
- Basic Linux command-line knowledge

### 30-Second Setup
```bash
# Clone or create project directory
mkdir chaos-security && cd chaos-security

# Create virtual environment
python3.10 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start vulnerable test system
docker-compose up -d

# Run first chaos test
python orchestrator.py --scenario basic_auth_failure.yaml

# View results
cat results/report.html
```

---

## Architecture Details

### Component Interaction Diagram
```
┌─────────────────────────────────────────────────────────┐
│                  Test Orchestrator                       │
│  (Reads scenarios, schedules faults, coordinates run)    │
└──────────────────┬──────────────────────────────────────┘
                   │
        ┌──────────┼──────────┐
        │          │          │
        ▼          ▼          ▼
    ┌────────┐ ┌─────────┐ ┌──────────────┐
    │ Fault  │ │ Workload│ │ Monitoring   │
    │Injector│ │Generator│ │ (Logs+Traffic)
    └────┬───┘ └────┬────┘ └──────┬───────┘
         │          │             │
         └──────────┼─────────────┘
                    │
            ┌───────▼────────┐
            │ Vulnerable     │
            │ Microservices  │
            │ (Test System)  │
            └────────────────┘
                    │
         ┌──────────┼──────────┐
         ▼          ▼          ▼
    [Logs]    [Traffic]  [State Changes]
         │          │          │
         └──────────┼──────────┘
                    │
            ┌───────▼──────────┐
            │ Assertion Engine │
            │ (Verify Security │
            │  Properties)     │
            └────────┬─────────┘
                     │
            ┌────────▼────────┐
            │Report Generator │
            │ (HTML + JSON)   │
            └─────────────────┘
```

### Data Flow
```
Scenario (YAML)
    ↓
Orchestrator parses scenario
    ↓
├─→ Fault Injector: Schedule faults at T+10s, T+30s, etc.
├─→ Workload Generator: Execute normal client operations
├─→ Log Aggregator: Stream logs from all containers
└─→ Traffic Monitor: Capture inter-service calls
    ↓
    During test (30 seconds):
    - Fault 1 injects auth service latency
    - Workload tries login (timeout)
    - Log Aggregator captures timeout error
    - Traffic Monitor records failed auth attempt
    - Anomaly detector flags unusual pattern
    ↓
    At T+35s (test complete):
    - Assertion Engine checks: "Did unauthorized access occur?"
    - Report Generator creates findings
    - Severity classifier marks as "High" or "Critical"
    ↓
Output: HTML report + JSON data
```

---

## Setting Up the Vulnerable Test System

### Directory Structure
```
chaos-security/
├── docker-compose.yml          # Service definitions
├── services/
│   ├── api-gateway/
│   │   ├── Dockerfile
│   │   └── app.py
│   ├── auth-service/
│   │   ├── Dockerfile
│   │   └── auth.py
│   ├── user-service/
│   │   └── users.py
│   ├── data-service/
│   │   └── data.py
│   └── log-service/
│       └── logs.py
├── framework/
│   ├── orchestrator.py
│   ├── fault_injector.py
│   ├── log_aggregator.py
│   ├── traffic_monitor.py
│   ├── assertions.py
│   └── report_generator.py
├── scenarios/
│   ├── basic_auth_failure.yaml
│   ├── cascading_failure.yaml
│   └── credential_leak.yaml
└── results/
    └── [generated reports]
```

### Docker Compose Configuration
```yaml
version: '3.8'

services:
  api-gateway:
    build: ./services/api-gateway
    ports:
      - "8000:8000"
    environment:
      - AUTH_SERVICE_URL=http://auth-service:8001
      - USER_SERVICE_URL=http://user-service:8002
    depends_on:
      - auth-service
      - user-service
    networks:
      - chaos-net

  auth-service:
    build: ./services/auth-service
    ports:
      - "8001:8001"
    environment:
      - SECRET_KEY="hardcoded-secret-key"  # INTENTIONAL VULNERABILITY
      - DB_HOST=postgres
    depends_on:
      - postgres
    networks:
      - chaos-net

  user-service:
    build: ./services/user-service
    ports:
      - "8002:8002"
    environment:
      - DB_HOST=postgres
      - AUTH_SERVICE_URL=http://auth-service:8001
    networks:
      - chaos-net

  data-service:
    build: ./services/data-service
    ports:
      - "8003:8003"
    environment:
      - DB_HOST=postgres
      - AUTH_SERVICE_URL=http://auth-service:8001
    networks:
      - chaos-net

  log-service:
    image: elasticsearch:8.0.0
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
    ports:
      - "9200:9200"
    networks:
      - chaos-net

  postgres:
    image: postgres:14
    environment:
      - POSTGRES_DB=chaos_test
      - POSTGRES_USER=chaos
      - POSTGRES_PASSWORD=chaos123  # INTENTIONAL VULNERABILITY
    ports:
      - "5432:5432"
    networks:
      - chaos-net

networks:
  chaos-net:
    driver: bridge
```

### Example Vulnerable Service: Auth Service
```python
# services/auth-service/auth.py
from flask import Flask, request, jsonify
import jwt
import os
from datetime import datetime, timedelta

app = Flask(__name__)

# VULNERABILITY: Hardcoded secret key (should be in environment, rotated)
SECRET_KEY = os.getenv("SECRET_KEY", "hardcoded-secret-key")

# VULNERABILITY: No token revocation list
active_tokens = set()

@app.route('/login', methods=['POST'])
def login():
    username = request.json.get('username')
    password = request.json.get('password')
    
    # VULNERABILITY: No password validation (accept any password)
    
    # VULNERABILITY: Token contains no expiration enforcement
    payload = {
        'username': username,
        'iat': datetime.utcnow(),
        'exp': datetime.utcnow() + timedelta(hours=24)
    }
    
    token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')
    active_tokens.add(token)
    
    # VULNERABILITY: Logging entire token (credential leak)
    app.logger.info(f"Login successful for {username}. Token: {token}")
    
    return jsonify({'token': token}), 200

@app.route('/validate', methods=['POST'])
def validate():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        return jsonify({'valid': True, 'user': payload['username']}), 200
    except jwt.InvalidTokenError as e:
        # VULNERABILITY: Detailed error messages reveal token format
        app.logger.error(f"Token validation failed: {str(e)}")
        return jsonify({'valid': False, 'error': str(e)}), 401

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8001, debug=True)  # VULNERABILITY: Debug mode
```

---

## Building Core Components

### 1. Orchestrator (Coordinator)
```python
# framework/orchestrator.py
import yaml
import json
import time
import subprocess
from datetime import datetime
import logging

class Orchestrator:
    def __init__(self, scenario_file):
        with open(scenario_file) as f:
            self.scenario = yaml.safe_load(f)
        self.logger = logging.getLogger('orchestrator')
        self.start_time = None
        self.events = []
    
    def run(self):
        """Execute a chaos engineering test scenario"""
        self.logger.info(f"Starting scenario: {self.scenario['name']}")
        self.start_time = datetime.now()
        
        try:
            # Phase 1: Baseline (collect normal behavior)
            self.logger.info("Phase 1: Baseline collection (30s)")
            self._baseline_phase()
            
            # Phase 2: Fault injection
            self.logger.info("Phase 2: Fault injection")
            self._injection_phase()
            
            # Phase 3: Recovery observation
            self.logger.info("Phase 3: Recovery monitoring (30s)")
            self._recovery_phase()
            
            # Phase 4: Analysis
            self.logger.info("Phase 4: Analyzing results")
            self._analyze()
            
        finally:
            self._cleanup()
    
    def _baseline_phase(self):
        """Run workload without faults for 30 seconds"""
        workload = self.scenario.get('workload', {})
        
        # Start workload generator
        subprocess.Popen([
            'python', 'workload_generator.py',
            '--duration', '30',
            '--requests_per_second', str(workload.get('rps', 10))
        ])
        
        time.sleep(30)
    
    def _injection_phase(self):
        """Inject faults according to scenario"""
        faults = self.scenario.get('faults', [])
        
        for fault in faults:
            delay = fault.get('delay_seconds', 0)
            time.sleep(delay)
            
            self.logger.info(f"Injecting fault: {fault['type']}")
            fault_id = self._inject_fault(fault)
            self.events.append({
                'timestamp': datetime.now().isoformat(),
                'type': 'fault_injected',
                'fault_id': fault_id,
                'fault_spec': fault
            })
            
            # Keep fault active for specified duration
            duration = fault.get('duration_seconds', 10)
            time.sleep(duration)
            
            # Remove fault
            self._remove_fault(fault_id)
            self.events.append({
                'timestamp': datetime.now().isoformat(),
                'type': 'fault_removed',
                'fault_id': fault_id
            })
    
    def _inject_fault(self, fault):
        """Delegate to appropriate fault injector"""
        fault_type = fault['type']
        target = fault['target']
        
        if fault_type == 'network_latency':
            return self._inject_latency(target, fault['latency_ms'])
        elif fault_type == 'service_crash':
            return self._inject_crash(target)
        elif fault_type == 'credential_leak':
            return self._inject_credential_leak(target)
        else:
            raise ValueError(f"Unknown fault type: {fault_type}")
    
    def _inject_latency(self, service, ms):
        """Inject network latency using tc (traffic control)"""
        container_name = f"{service}"
        
        # Use Docker to run tc inside container
        cmd = [
            'docker', 'exec', container_name,
            'tc', 'qdisc', 'add', 'dev', 'eth0', 'root', 'netem', f'delay', f'{ms}ms'
        ]
        subprocess.run(cmd, check=True)
        
        return f"latency_{service}_{int(time.time())}"
    
    def _inject_crash(self, service):
        """Stop a service container"""
        subprocess.run(['docker', 'pause', service], check=True)
        return f"crash_{service}_{int(time.time())}"
    
    def _inject_credential_leak(self, service):
        """Inject credentials into logs"""
        container_name = service
        
        # Execute command inside container to log fake credentials
        cmd = [
            'docker', 'exec', container_name,
            'logger', 'CRITICAL: Database password is: hardcoded_password_123'
        ]
        subprocess.run(cmd, check=True)
        
        return f"cred_leak_{service}_{int(time.time())}"
    
    def _remove_fault(self, fault_id):
        """Clean up injected fault"""
        # Implementation depends on fault type
        pass
    
    def _recovery_phase(self):
        """Monitor system recovery for 30 seconds"""
        time.sleep(30)
    
    def _analyze(self):
        """Collect logs and evaluate assertions"""
        from assertions import AssertionEngine
        from report_generator import ReportGenerator
        
        # Fetch all logs and traffic data
        logs = self._get_logs()
        traffic = self._get_traffic()
        
        # Evaluate security properties
        engine = AssertionEngine(logs, traffic, self.scenario)
        violations = engine.evaluate()
        
        # Generate report
        report = ReportGenerator(
            scenario=self.scenario,
            events=self.events,
            violations=violations,
            logs=logs,
            traffic=traffic
        )
        
        report.write('results/report.html')
        report.write('results/report.json')
    
    def _cleanup(self):
        """Restore system to baseline"""
        self.logger.info("Cleaning up...")
        subprocess.run(['docker', 'compose', 'restart'], check=True)

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenario', required=True, help='Path to scenario YAML')
    args = parser.parse_args()
    
    orchestrator = Orchestrator(args.scenario)
    orchestrator.run()
```

### 2. Security Assertions Engine
```python
# framework/assertions.py
import re
from enum import Enum

class Severity(Enum):
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4

class SecurityAssertion:
    """Represents a security property to verify"""
    def __init__(self, name, description, check_func, severity=Severity.HIGH):
        self.name = name
        self.description = description
        self.check_func = check_func
        self.severity = severity
    
    def evaluate(self, logs, traffic):
        """Run assertion check. Returns (passed: bool, evidence: dict)"""
        return self.check_func(logs, traffic)

class AssertionEngine:
    def __init__(self, logs, traffic, scenario):
        self.logs = logs
        self.traffic = traffic
        self.scenario = scenario
        self.violations = []
        
        # Define security assertions
        self.assertions = self._build_assertions()
    
    def _build_assertions(self):
        """Create domain-specific assertions"""
        return [
            SecurityAssertion(
                name="No Unauthorized Data Access",
                description="User A should not access User B's data",
                check_func=self._check_data_access,
                severity=Severity.CRITICAL
            ),
            SecurityAssertion(
                name="Credentials Not Exposed in Logs",
                description="API keys, tokens, passwords must not appear in logs",
                check_func=self._check_credential_leaks,
                severity=Severity.CRITICAL
            ),
            SecurityAssertion(
                name="Failed Auth Blocks Access",
                description="Unauthenticated requests should be rejected",
                check_func=self._check_auth_enforcement,
                severity=Severity.CRITICAL
            ),
            SecurityAssertion(
                name="Service Isolation Maintained",
                description="Compromised service should not access secrets of others",
                check_func=self._check_service_isolation,
                severity=Severity.HIGH
            ),
        ]
    
    def _check_data_access(self, logs, traffic):
        """Check if users only access their own data"""
        violations = []
        
        for req in traffic:
            if req['endpoint'].startswith('/data/'):
                user_id = req.get('user_id')
                accessed_id = req['endpoint'].split('/')[-1]
                
                if user_id and user_id != accessed_id:
                    violations.append({
                        'type': 'unauthorized_access',
                        'user': user_id,
                        'accessed_resource': accessed_id,
                        'timestamp': req['timestamp'],
                        'http_method': req['method'],
                        'http_status': req['status']
                    })
        
        return (len(violations) == 0, {'violations': violations})
    
    def _check_credential_leaks(self, logs, traffic):
        """Check logs for exposed credentials"""
        violations = []
        
        # Patterns for common credentials
        patterns = {
            'api_key': r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']?([a-z0-9]{20,})',
            'password': r'(?i)(password|passwd|pwd)\s*[=:]\s*["\']?(\S+)["\']?',
            'token': r'(?i)(token|bearer)\s+([a-z0-9._-]+)',
            'jwt': r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+',
        }
        
        for log_entry in logs:
            message = log_entry.get('message', '')
            
            for cred_type, pattern in patterns.items():
                matches = re.finditer(pattern, message)
                for match in matches:
                    violations.append({
                        'type': 'credential_exposure',
                        'credential_type': cred_type,
                        'service': log_entry['service'],
                        'timestamp': log_entry['timestamp'],
                        'log_level': log_entry['level'],
                        'context': message[:200]
                    })
        
        return (len(violations) == 0, {'violations': violations})
    
    def _check_auth_enforcement(self, logs, traffic):
        """Verify unauthenticated requests are rejected"""
        violations = []
        
        for req in traffic:
            # Protected endpoints should reject requests without auth
            if req['endpoint'].startswith('/data/') or req['endpoint'].startswith('/user/'):
                if 'Authorization' not in req.get('headers', {}):
                    if req['status'] != 401:  # Should be unauthorized
                        violations.append({
                            'type': 'auth_bypass',
                            'endpoint': req['endpoint'],
                            'method': req['method'],
                            'status_code': req['status'],
                            'timestamp': req['timestamp']
                        })
        
        return (len(violations) == 0, {'violations': violations})
    
    def _check_service_isolation(self, logs, traffic):
        """Verify services don't access each other's secrets"""
        violations = []
        
        # Define trust boundaries
        boundaries = {
            'data-service': ['api-gateway', 'user-service'],  # Only these can call data-service
        }
        
        for req in traffic:
            target_service = req.get('target_service')
            source_service = req.get('source_service')
            
            if target_service in boundaries:
                if source_service not in boundaries[target_service]:
                    violations.append({
                        'type': 'isolation_violation',
                        'source': source_service,
                        'target': target_service,
                        'endpoint': req['endpoint'],
                        'timestamp': req['timestamp']
                    })
        
        return (len(violations) == 0, {'violations': violations})
    
    def evaluate(self):
        """Run all assertions and return violations"""
        results = []
        
        for assertion in self.assertions:
            passed, evidence = assertion.evaluate(self.logs, self.traffic)
            
            result = {
                'assertion': assertion.name,
                'passed': passed,
                'severity': assertion.severity.name,
                'description': assertion.description,
                'evidence': evidence
            }
            
            results.append(result)
            
            if not passed:
                self.violations.append(result)
        
        return results
```

### 3. Example Test Scenario (YAML)
```yaml
# scenarios/credential_leak.yaml
name: "Credential Leak Under Auth Service Failure"
description: |
  This scenario tests whether the system leaks credentials when
  the authentication service becomes slow. If auth service is slow,
  does the API gateway log full requests (including tokens)?

duration_seconds: 120

workload:
  type: realistic_client
  rps: 10  # 10 requests per second
  operations:
    - login
    - browse_profile
    - access_data

faults:
  - type: network_latency
    target: auth-service
    delay_seconds: 5
    latency_ms: 5000  # 5 second delay
    duration_seconds: 30
  
  - type: credential_leak
    target: api-gateway
    delay_seconds: 40
    duration_seconds: 20

security_properties:
  - property: "no_credential_leaks"
    description: "No API keys or tokens should appear in logs"
    severity: critical
  
  - property: "auth_not_bypassed"
    description: "Delayed auth service should not cause auth bypass"
    severity: critical
  
  - property: "data_isolation"
    description: "Users should not access each other's data"
    severity: critical

expected_violations:
  - type: "credential_exposure"
    where: "api-gateway logs"
    why: "API gateway logs full request including auth header"
    severity: "critical"
```

---

## Running Your First Test

### Step 1: Start the Test System
```bash
docker-compose up -d
docker-compose logs -f  # Monitor startup
```

### Step 2: Verify Services Are Running
```bash
# Test each service
curl http://localhost:8000/health  # API Gateway
curl http://localhost:8001/health  # Auth Service
curl http://localhost:8002/health  # User Service
```

### Step 3: Run a Test Scenario
```bash
python framework/orchestrator.py --scenario scenarios/credential_leak.yaml
```

### Step 4: View Results
```bash
# Open in browser
open results/report.html

# Or view JSON data
cat results/report.json | jq .
```

---

## Expected Results

### Sample Report Output
```json
{
  "test_name": "Credential Leak Under Auth Service Failure",
  "timestamp": "2026-04-07T14:30:45Z",
  "duration_seconds": 120,
  "overall_status": "FINDINGS_DETECTED",
  
  "summary": {
    "total_assertions": 4,
    "passed": 2,
    "failed": 2,
    "critical_violations": 2,
    "high_violations": 0,
    "medium_violations": 0
  },
  
  "violations": [
    {
      "id": "CRED_LEAK_001",
      "assertion": "Credentials Not Exposed in Logs",
      "severity": "CRITICAL",
      "triggered_at": "2026-04-07T14:31:12Z",
      "description": "API keys found in API gateway logs",
      "evidence": {
        "service": "api-gateway",
        "log_entry": "Received request: POST /data Authorization: Bearer eyJhbGci...",
        "credential_type": "jwt_token",
        "exposure_count": 147
      },
      "causal_trace": [
        {
          "event": "auth-service latency injection",
          "timestamp": "2026-04-07T14:31:05Z",
          "impact": "API gateway retried requests, logging full headers"
        },
        {
          "event": "token leak detected in logs",
          "timestamp": "2026-04-07T14:31:12Z",
          "impact": "Attacker could harvest tokens from logs"
        }
      ],
      "remediation": [
        "Sanitize logs to exclude Authorization headers",
        "Implement structured logging with field masks",
        "Use log redaction library (e.g., pythonjsonlogger with filters)"
      ]
    },
    {
      "id": "AUTH_BYPASS_001",
      "assertion": "Failed Auth Blocks Access",
      "severity": "CRITICAL",
      "triggered_at": "2026-04-07T14:31:45Z",
      "description": "Data requests succeeded without valid auth during service degradation",
      "evidence": {
        "endpoint": "/data/user/123",
        "method": "GET",
        "http_status": 200,
        "auth_header": "missing",
        "timestamps": ["2026-04-07T14:31:40Z", "2026-04-07T14:31:42Z"]
      },
      "remediation": [
        "Implement auth timeout (fail closed, not open)",
        "Add circuit breaker for auth service",
        "Use cached auth decisions with short TTL"
      ]
    }
  ],
  
  "timeline": {
    "t+0s": "Baseline phase started",
    "t+30s": "Baseline complete, injection phase started",
    "t+35s": "Latency injected on auth-service (5s delay)",
    "t+40s": "First timeout detected in logs",
    "t+45s": "Credential leak detected",
    "t+65s": "Latency fault removed",
    "t+95s": "Injection phase complete",
    "t+125s": "Recovery monitoring complete"
  },
  
  "recommendations": [
    {
      "priority": "CRITICAL",
      "action": "Remove tokens from logs immediately",
      "effort": "2 hours",
      "impact": "Prevents credential harvesting attack"
    },
    {
      "priority": "CRITICAL",
      "action": "Implement fail-closed auth (reject if auth service unavailable)",
      "effort": "8 hours",
      "impact": "Prevents bypass during degradation"
    },
    {
      "priority": "HIGH",
      "action": "Add auth service health monitoring and alerts",
      "effort": "4 hours",
      "impact": "Earlier detection of auth failures"
    }
  ]
}
```

---

## Next Steps

1. **Expand Test System**: Add more services and more complex vulnerability chains
2. **Build Additional Assertions**: Create assertions specific to your security model
3. **Integrate with CI/CD**: Run chaos tests on every deployment
4. **Develop Web UI**: Build dashboard to visualize test results and trends
5. **Scale Testing**: Adapt framework for production-like distributed systems

---

## Resources

- **Code Templates**: See `framework/` directory for skeleton implementations
- **Docker Networking**: Use service discovery and DNS for inter-service calls
- **Monitoring**: Integrate Prometheus, Grafana, or custom dashboards
- **Test Data**: Generate realistic user scenarios in `workload_generator.py`

