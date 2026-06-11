/**
 * Firebase Configuration for Kaling (kaling.cloud)
 */
export const firebaseConfig = {
  apiKey: "AIzaSyADGG-DTQKUy9hP-0DpfJebqQZGMAS-xtA",
  authDomain: "ar-drawing-c167d.firebaseapp.com",
  projectId: "ar-drawing-c167d",
  storageBucket: "ar-drawing-c167d.firebasestorage.app",
  messagingSenderId: "1064452971616",
  appId: "1:1064452971616:web:25cd14912af6cc8b9cb705",
  measurementId: "G-PFKHV13HP9"
};

/**
 * Admin emails authorized to access the management panel.
 */
export const ADMIN_EMAILS = ["traderfinn0312@gmail.com", "dinhhoangvan.hh@gmail.com"];

/**
 * FIRESTORE SECURITY RULES
 * Copy into Firebase Console → Firestore → Rules → Publish
 *
 * rules_version = '2';
 * service cloud.firestore {
 *   match /databases/{database}/documents {
 *     function isAdmin() {
 *       return request.auth != null
 *         && request.auth.token.email in ["traderfinn0312@gmail.com"];
 *     }
 *
 *     match /users/{userId} {
 *       allow read: if request.auth != null && request.auth.uid == userId;
 *       allow create: if request.auth != null && request.auth.uid == userId;
 *       allow update: if isAdmin();
 *     }
 *
 *     match /orders/{orderId} {
 *       allow read: if request.auth != null
 *         && (resource.data.userId == request.auth.uid || isAdmin());
 *       allow create: if request.auth != null;
 *       allow update: if isAdmin();
 *     }
 *
 *     match /topups/{topupId} {
 *       allow read: if request.auth != null
 *         && (resource.data.userId == request.auth.uid || isAdmin());
 *       allow create: if request.auth != null;
 *       allow update: if isAdmin();
 *     }
 *
 *     match /bots/{botId} {
 *       allow read: if isAdmin();
 *       allow write: if isAdmin();
 *     }
 *
 *     match /referralCodes/{codeId} {
 *       allow read: if request.auth != null;
 *       allow write: if isAdmin();
 *     }
 *
 *     match /referralEarnings/{earningId} {
 *       allow read: if request.auth != null
 *         && (resource.data.referrerId == request.auth.uid || isAdmin());
 *       allow write: if isAdmin();
 *     }
 *
 *     match /referralAllowlist/{emailId} {
 *       allow read: if request.auth != null && (
 *         request.auth.token.email.lower() == emailId || isAdmin()
 *       );
 *       allow write: if isAdmin();
 *     }
 *
 *     match /settings/{docId} {
 *       allow read: if isAdmin();
 *       allow write: if isAdmin();
 *     }
 *   }
 * }
 */
