# Credentials are supplied through OCI_* environment variables by Doppler.
# Do not add private keys, tokens, SSH connections or provisioners here.
provider "oci" {
  region = var.oci_region
}
