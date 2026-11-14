/**
 * The app shell — one screen.
 *
 * Everything the old UI stacked on this page (masthead, narration, story rail, lab, feed) is gone.
 * A visitor should be able to answer three questions without scrolling: what is this, what needs
 * me, and what did the engine do. Those live in `Inbox`; the network log lives in the inspector.
 */

import { Inbox } from "./Inbox";

export default function App() {
  return <Inbox />;
}
