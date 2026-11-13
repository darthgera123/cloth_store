export const sessionPath = (code: string) => `sessions/${code.toUpperCase()}`;
export const metaPath = (code: string) => `${sessionPath(code)}/meta`;
export const boardPath = (code: string) => `${sessionPath(code)}/board`;
export const teamsPath = (code: string) => `${sessionPath(code)}/teams`;
export const teamPath = (code: string, teamId: string) => `${teamsPath(code)}/${teamId}`;
export const guessesPath = (code: string) => `${sessionPath(code)}/guesses`;
export const teamGuessesPath = (code: string, teamId: string) =>
  `${guessesPath(code)}/${teamId}`;
export const guessPath = (code: string, teamId: string, roundId: string) =>
  `${teamGuessesPath(code, teamId)}/${roundId}`;
