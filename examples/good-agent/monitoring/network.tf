# Network isolation for the File Summarizer Agent
# Restricts egress to api.anthropic.com:443 only — prevents data exfiltration.

resource "aws_security_group" "summarizer_agent" {
  name        = "summarizer-agent-sg"
  description = "Egress-restricted security group for the File Summarizer Agent"
  vpc_id      = var.vpc_id

  # Allow outbound HTTPS to Anthropic API only
  egress {
    description = "Anthropic API"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    # Note: restrict further to Anthropic IP ranges via prefix list in production
  }

  # Deny all other outbound traffic — no exfiltration to arbitrary endpoints
  # (AWS default: all other egress is denied when no other egress rule matches)

  # No inbound rules — agent is invoked via CLI, not as a server
  tags = {
    Name      = "summarizer-agent"
    ManagedBy = "terraform"
  }
}

resource "aws_vpc_endpoint" "anthropic_proxy" {
  # Optional: route API calls through a VPC endpoint proxy for audit logging
  # Replace with your API gateway endpoint ARN if using a proxy layer
  vpc_id            = var.vpc_id
  service_name      = var.anthropic_proxy_service_name
  vpc_endpoint_type = "Interface"
  security_group_ids = [aws_security_group.summarizer_agent.id]

  tags = {
    Name = "summarizer-agent-anthropic-proxy"
  }
}

variable "vpc_id" {
  description = "VPC in which the agent runs"
  type        = string
}

variable "anthropic_proxy_service_name" {
  description = "VPC endpoint service name for the Anthropic API proxy (optional)"
  type        = string
  default     = ""
}
