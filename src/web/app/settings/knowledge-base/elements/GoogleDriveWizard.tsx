"use client";

import { useState } from "react";
import { X, ChevronLeft, ChevronRight, Check } from "lucide-react";
import {
  useConnectGoogleDrive,
  type ConnectGoogleDrivePayload,
} from "@/lib/hooks/useGoogleDrive";

type WizardStep = 1 | 2 | 3;

interface GoogleDriveWizardProps {
  onClose: () => void;
}

/**
 * FE-030: Google Drive Connection Wizard (3 steps).
 * Step 1: Connection Details (name, folder ID, service account email)
 * Step 2: Credentials (vault reference path)
 * Step 3: Review and Connect
 */
export function GoogleDriveWizard({ onClose }: GoogleDriveWizardProps) {
  const [step, setStep] = useState<WizardStep>(1);

  // Step 1: Connection Details
  const [name, setName] = useState("");
  const [folderId, setFolderId] = useState("");
  const [serviceAccountEmail, setServiceAccountEmail] = useState("");

  // Step 2: Credentials
  const [credentialRef, setCredentialRef] = useState("");

  const connectMutation = useConnectGoogleDrive();

  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  const canProceedStep1 =
    name.trim().length > 0 &&
    folderId.trim().length > 0 &&
    emailRegex.test(serviceAccountEmail.trim());

  // Enforce vault:// prefix so users can't accidentally paste raw JSON keys
  const vaultRefPattern = /^vault:\/\/.+/;
  const canProceedStep2 = vaultRefPattern.test(credentialRef.trim());

  function handleNext() {
    if (step < 3) setStep((step + 1) as WizardStep);
  }

  function handleBack() {
    if (step > 1) setStep((step - 1) as WizardStep);
  }

  async function handleConnect() {
    const payload: ConnectGoogleDrivePayload = {
      name: name.trim(),
      folder_id: folderId.trim(),
      service_account_email: serviceAccountEmail.trim(),
      credential_ref: credentialRef.trim(),
    };

    await connectMutation.mutateAsync(payload);
    onClose();
  }

  const progressWidth = step === 1 ? "33.3%" : step === 2 ? "66.6%" : "100%";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
      <div className="w-full max-w-[640px] rounded-card border border-border bg-bg-surface">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 className="text-section-heading text-text-primary">
              Connect Google Drive
            </h2>
            <p className="mt-0.5 text-[11px] text-text-faint">
              Step {step} of 3
            </p>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Progress bar */}
        <div className="h-1 w-full bg-bg-elevated">
          <div
            className="h-full bg-accent transition-all duration-200"
            style={{ width: progressWidth }}
          />
        </div>

        {/* Content */}
        <div className="p-5">
          {/* Step 1: Connection Details */}
          {step === 1 && (
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                  Connection Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Engineering Docs"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                />
              </div>

              <div>
                <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                  Google Drive Folder ID
                </label>
                <input
                  type="text"
                  value={folderId}
                  onChange={(e) => setFolderId(e.target.value)}
                  placeholder="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74O"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-body-default text-text-muted placeholder:text-text-faint focus:border-accent focus:outline-none"
                />
                <p className="mt-1 text-xs text-text-faint">
                  Found in the Google Drive folder URL after /folders/
                </p>
              </div>

              <div>
                <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                  Service Account Email
                </label>
                <input
                  type="email"
                  value={serviceAccountEmail}
                  onChange={(e) => setServiceAccountEmail(e.target.value)}
                  placeholder="mingai-sa@project-id.iam.gserviceaccount.com"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-body-default text-text-muted placeholder:text-text-faint focus:border-accent focus:outline-none"
                />
                <p className="mt-1 text-xs text-text-faint">
                  The Google Cloud service account that has read access to the
                  folder
                </p>
              </div>
            </div>
          )}

          {/* Step 2: Credentials */}
          {step === 2 && (
            <div className="space-y-4">
              <div className="rounded-card bg-bg-elevated p-4">
                <p className="text-body-default text-text-muted">
                  Your service account JSON key must be stored in your
                  organization&apos;s vault. Enter the vault reference path
                  below.
                </p>
              </div>

              <div>
                <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                  Credential Reference
                </label>
                <input
                  type="text"
                  value={credentialRef}
                  onChange={(e) => setCredentialRef(e.target.value)}
                  placeholder="vault://secrets/google-drive/service-account-key"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-body-default text-text-muted placeholder:text-text-faint focus:border-accent focus:outline-none"
                />
                <p className="mt-1 text-xs text-text-faint">
                  The vault path where the service account JSON key is stored
                </p>
              </div>
            </div>
          )}

          {/* Step 3: Review */}
          {step === 3 && (
            <div className="space-y-4">
              <p className="text-body-default text-text-muted">
                Review the details below and confirm the connection.
              </p>

              <div className="rounded-card border border-border bg-bg-elevated p-4">
                <dl className="space-y-3">
                  <div className="flex justify-between">
                    <dt className="text-[11px] uppercase tracking-wider text-text-faint">
                      Name
                    </dt>
                    <dd className="text-body-default text-text-primary">{name}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-[11px] uppercase tracking-wider text-text-faint">
                      Folder ID
                    </dt>
                    <dd className="font-mono text-body-default text-text-muted">
                      {folderId}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-[11px] uppercase tracking-wider text-text-faint">
                      Service Account
                    </dt>
                    <dd className="font-mono text-body-default text-text-muted">
                      {serviceAccountEmail}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-[11px] uppercase tracking-wider text-text-faint">
                      Credential Ref
                    </dt>
                    <dd className="font-mono text-body-default text-text-muted">
                      {credentialRef}
                    </dd>
                  </div>
                </dl>
              </div>

              {connectMutation.isError && (
                <div className="rounded-control border border-alert/30 bg-alert-dim p-3">
                  <p className="text-xs text-alert">
                    {connectMutation.error instanceof Error
                      ? connectMutation.error.message
                      : "Failed to connect Google Drive"}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-between border-t border-border px-5 py-3">
          <div>
            {step > 1 && (
              <button
                type="button"
                onClick={handleBack}
                disabled={connectMutation.isPending}
                className="flex items-center gap-1 rounded-control border border-border px-3 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated disabled:opacity-30"
              >
                <ChevronLeft size={14} />
                Back
              </button>
            )}
          </div>

          <div className="flex gap-2">
            {step === 1 && (
              <button
                type="button"
                onClick={onClose}
                className="rounded-control border border-border px-3 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated"
              >
                Cancel
              </button>
            )}

            {step < 3 && (
              <button
                type="button"
                onClick={handleNext}
                disabled={
                  (step === 1 && !canProceedStep1) ||
                  (step === 2 && !canProceedStep2)
                }
                className="flex items-center gap-1 rounded-control bg-accent px-4 py-1.5 text-body-default font-semibold text-bg-base transition-opacity disabled:opacity-30"
              >
                Next
                <ChevronRight size={14} />
              </button>
            )}

            {step === 3 && (
              <button
                type="button"
                onClick={handleConnect}
                disabled={connectMutation.isPending}
                className="flex items-center gap-1 rounded-control bg-accent px-4 py-1.5 text-body-default font-semibold text-bg-base transition-opacity disabled:opacity-30"
              >
                {connectMutation.isPending ? (
                  "Connecting..."
                ) : (
                  <>
                    <Check size={14} />
                    Connect
                  </>
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
