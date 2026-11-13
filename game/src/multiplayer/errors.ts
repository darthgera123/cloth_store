export function friendlyFirebaseError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error ?? "");
  if (/permission[_\s-]?denied/i.test(message)) {
    return "Firebase denied access. Deploy the Realtime Database rules for this project.";
  }
  if (/network|offline|unavailable|fetch/i.test(message)) {
    return "Firebase is unreachable. Check the network connection.";
  }
  if (/auth|credential/i.test(message)) {
    return "Firebase sign-in failed. Enable Anonymous Authentication in the console.";
  }
  return message || "Firebase request failed.";
}
