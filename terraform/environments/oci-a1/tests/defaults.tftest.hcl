mock_provider "oci" {}

run "empty_by_default" {
  command = plan

  variables {
    oci_region = "us-ashburn-1"
  }

  assert {
    condition     = length(output.nodes) == 0
    error_message = "An unconfigured environment must expose no managed nodes."
  }
}
