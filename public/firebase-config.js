/**
 * Firebase Configuration for MotionAI Studio
 * Replace the placeholder values with your actual Firebase project config.
 */
export const firebaseConfig = {
  apiKey: "AIzaSyA1Fqy_hbOJc_N-Dcy0v5jiQ7kLRaIUKi4",
  authDomain: "motionai-studio-76be9.firebaseapp.com",
  projectId: "motionai-studio-76be9",
  storageBucket: "motionai-studio-76be9.firebasestorage.app",
  messagingSenderId: "910538701040",
  appId: "1:910538701040:web:a30c3b7f20c504dc592a35",
  measurementId: "G-E71335FCYN"
};

/**
 * Admin emails authorized to access the management panel.
 */
export const ADMIN_EMAILS = ["traderfinn0312@gmail.com", "dinhhoangvan.hh@gmail.com"];

/**
 * FIRESTORE SECURITY RULES (Example)
 * Copy and paste these into your Firebase Console -> Firestore -> Rules
 *
 * rules_version = '2';
 * service cloud.firestore {
 *   match /databases/{database}/documents {
 *     // Function to check if user is admin
 *     function isAdmin() {
 *       return request.auth != null && request.auth.token.email in ["your-email@gmail.com"];
 *     }
 *
 *     // Users can read/write their own profile (but not direct coin updates)
 *     match /users/{userId} {
 *       allow read: if request.auth != null && request.auth.uid == userId;
 *       allow create: if request.auth != null && request.auth.uid == userId;
 *       allow update: if isAdmin(); // Only admin can update coins/profile
 *     }
 *
 *     // Orders
 *     match /orders/{orderId} {
 *       allow read: if request.auth != null && (resource.data.userId == request.auth.uid || isAdmin());
 *       allow create: if request.auth != null;
 *       allow update: if isAdmin();
 *     }
 *
 *     // Topup requests
 *     match /topups/{topupId} {
 *       allow read: if request.auth != null && (resource.data.userId == request.auth.uid || isAdmin());
 *       allow create: if request.auth != null;
 *       allow update: if isAdmin();
 *     }
 *   }
 * }
 */
